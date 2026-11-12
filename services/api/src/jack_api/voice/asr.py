"""Local speech recognition (faster-whisper / CTranslate2, MIT; Whisper weights MIT).

Models are downloaded only when the user asks (Voice page → Download), into the app's
local data directory, and are then loaded with ``local_files_only=True`` so recognition
never touches the network.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np

log = logging.getLogger(__name__)

ModelName = Literal["tiny.en", "base.en", "small.en"]


@dataclass(frozen=True)
class ModelInfo:
    name: str
    repo: str
    size_mb: int
    purpose: str


MODELS: dict[str, ModelInfo] = {
    "tiny.en": ModelInfo("tiny.en", "Systran/faster-whisper-tiny.en", 75,
                         "Wake word; fastest command recognition"),
    "base.en": ModelInfo("base.en", "Systran/faster-whisper-base.en", 145,
                         "Commands on slower PCs"),
    "small.en": ModelInfo("small.en", "Systran/faster-whisper-small.en", 484,
                          "Commands (recommended accuracy)"),
}
WAKE_MODEL = "tiny.en"


@dataclass
class Transcript:
    text: str
    avg_logprob: float
    no_speech_prob: float


class Recognizer(Protocol):
    def available(self, model: str) -> bool: ...
    def transcribe(self, audio: np.ndarray, model: str, *, prompt: str | None = None
                   ) -> Transcript: ...


Status = Literal["not_downloaded", "downloading", "ready", "error"]


@dataclass
class ModelState:
    status: Status
    downloaded_mb: float = 0.0
    error: str | None = None


class ModelManager:
    """Downloads, verifies and loads Whisper models. Thread-safe."""

    def __init__(self, root: Path, publish: Callable[[str, Any], None],
                 cpu_threads: int | None = None) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._publish = publish
        self._lock = threading.Lock()
        self._states: dict[str, ModelState] = {}
        self._loaded: dict[str, Any] = {}
        self._cpu_threads = cpu_threads or max(1, min(4, (os.cpu_count() or 2) - 1))

    # ------------------------------------------------------------------ status
    def _model_dir(self, name: str) -> Path | None:
        """Path of a complete local snapshot, or None."""
        repo_dir = self.root / ("models--" + MODELS[name].repo.replace("/", "--"))
        snaps = repo_dir / "snapshots"
        if not snaps.is_dir():
            return None
        for snap in sorted(snaps.iterdir()):
            if (snap / "model.bin").exists() and (snap / "config.json").exists():
                return snap
        return None

    def state(self, name: str) -> ModelState:
        with self._lock:
            st = self._states.get(name)
            if st and st.status in ("downloading", "error"):
                if st.status == "downloading":
                    st.downloaded_mb = self._dir_mb(name)
                return ModelState(st.status, st.downloaded_mb, st.error)
        return ModelState("ready" if self._model_dir(name) else "not_downloaded")

    def available(self, model: str) -> bool:
        return model in MODELS and self._model_dir(model) is not None

    def _dir_mb(self, name: str) -> float:
        d = self.root / ("models--" + MODELS[name].repo.replace("/", "--"))
        if not d.exists():
            return 0.0
        total = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        return round(total / 1e6, 1)

    def snapshot(self) -> list[dict[str, Any]]:
        out = []
        for name, info in MODELS.items():
            st = self.state(name)
            out.append({"name": name, "size_mb": info.size_mb, "purpose": info.purpose,
                        "status": st.status, "downloaded_mb": st.downloaded_mb,
                        "error": st.error})
        return out

    # ------------------------------------------------------------------ download
    def download(self, name: str) -> bool:
        """Start a background download. Returns False if already present or in progress."""
        if name not in MODELS:
            raise KeyError(name)
        with self._lock:
            cur = self._states.get(name)
            if (cur and cur.status == "downloading") or self._model_dir(name):
                return False
            self._states[name] = ModelState("downloading")
        threading.Thread(target=self._download, args=(name,), name=f"asr-dl-{name}",
                         daemon=True).start()
        self._publish("voice.models", self.snapshot())
        return True

    def _download(self, name: str) -> None:
        try:
            from huggingface_hub import snapshot_download

            snapshot_download(MODELS[name].repo, cache_dir=str(self.root),
                              allow_patterns=["config.json", "model.bin", "tokenizer.json",
                                              "vocabulary.*", "preprocessor_config.json"])
            if self._model_dir(name) is None:
                raise RuntimeError("download finished but model files are missing")
            with self._lock:
                self._states.pop(name, None)
            log.info("speech model %s downloaded", name)
        except Exception as exc:  # noqa: BLE001 - network/disk errors are reported to the user
            log.warning("speech model %s download failed: %s", name, exc)
            with self._lock:
                self._states[name] = ModelState("error", error=str(exc)[:300])
        self._publish("voice.models", self.snapshot())

    def delete(self, name: str) -> None:
        with self._lock:
            self._loaded.pop(name, None)
            self._states.pop(name, None)
        d = self.root / ("models--" + MODELS[name].repo.replace("/", "--"))
        shutil.rmtree(d, ignore_errors=True)
        self._publish("voice.models", self.snapshot())

    # ------------------------------------------------------------------ inference
    def _model(self, name: str) -> Any:
        with self._lock:
            m = self._loaded.get(name)
        if m is not None:
            return m
        path = self._model_dir(name)
        if path is None:
            raise RuntimeError(f"speech model {name} is not downloaded")
        from faster_whisper import WhisperModel

        m = WhisperModel(str(path), device="cpu", compute_type="int8",
                         cpu_threads=self._cpu_threads, local_files_only=True)
        with self._lock:
            self._loaded[name] = m
        return m

    def transcribe(self, audio: np.ndarray, model: str, *, prompt: str | None = None
                   ) -> Transcript:
        m = self._model(model)
        segments, _info = m.transcribe(audio.astype(np.float32), language="en", beam_size=1,
                                       condition_on_previous_text=False,
                                       initial_prompt=prompt, vad_filter=False,
                                       without_timestamps=True)
        segs = list(segments)
        if not segs:
            return Transcript("", -10.0, 1.0)
        text = " ".join(s.text.strip() for s in segs).strip()
        avg = sum(s.avg_logprob for s in segs) / len(segs)
        nsp = max(s.no_speech_prob for s in segs)
        return Transcript(text, avg, nsp)

    def warm(self, name: str) -> None:
        """Load a model ahead of first use (avoids a multi-second pause on first command)."""
        if self.available(name):
            self._model(name)
