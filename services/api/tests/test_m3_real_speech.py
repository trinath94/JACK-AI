"""Real-model speech tests: actual Silero VAD + faster-whisper models on speech synthesised
with espeak-ng, fed frame by frame through the voice engine exactly as a microphone would.

Skipped unless JACK_TEST_MODELS_DIR contains tiny.en and small.en (Hugging Face cache layout)
and espeak-ng is installed. CI downloads the models for this suite.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from conftest import BASE, FakeAudio, FakeTts, wait_for
from jack_api.app import create_app
from jack_api.config import Settings
from jack_api.voice.asr import ModelManager

MODELS_DIR = os.environ.get("JACK_TEST_MODELS_DIR")
ESPEAK = shutil.which("espeak-ng")


def _have_models() -> bool:
    if not MODELS_DIR:
        return False
    mm = ModelManager(Path(MODELS_DIR), lambda *_: None)
    return mm.available("tiny.en") and mm.available("small.en")


pytestmark = pytest.mark.skipif(not (_have_models() and ESPEAK),
                                reason="needs JACK_TEST_MODELS_DIR (tiny.en, small.en) "
                                       "and espeak-ng")


def synth(text: str, tmp: Path, voice: str = "en-us", wpm: int = 150) -> np.ndarray:
    raw, out = tmp / "raw.wav", tmp / "16k.wav"
    subprocess.run([ESPEAK or "espeak-ng", "-v", voice, "-s", str(wpm), "-w", str(raw), text],  # noqa: S603
                   check=True)
    subprocess.run(["sox", str(raw), "-r", "16000", "-c", "1", "-b", "16", str(out)],  # noqa: S603,S607
                   check=True)
    with wave.open(str(out)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def feed(audio: FakeAudio, pcm: np.ndarray, silence_s: float = 1.2) -> None:
    pcm = np.concatenate([pcm, np.zeros(int(silence_s * 16000), np.int16)])
    for i in range(0, len(pcm) - 511, 512):
        audio._on_frame(pcm[i:i + 512].copy())  # type: ignore[misc]


@pytest.fixture
def real(tmp_path: Path, token: str, audio: FakeAudio, tts: FakeTts) -> Any:
    settings = Settings(session_token=token, port=8765, data_dir=tmp_path / "data",
                        models_dir=Path(MODELS_DIR or "."), health_interval_s=0.5)
    app = create_app(settings, audio_backend=audio, tts=tts)  # real VAD + real ASR
    with TestClient(app, base_url=BASE, headers={"Authorization": f"Bearer {token}"}) as c:
        yield c, app.state.svc.voice


def _last_task(c: TestClient) -> dict[str, Any]:
    return c.get("/v1/tasks").json()["items"][0]  # type: ignore[no-any-return]


def test_push_to_talk_real_recognition(real: Any, audio: FakeAudio, tmp_path: Path) -> None:
    c, engine = real
    c.post("/v1/voice/ptt/start", json={})
    feed(audio, synth("Build a professional corporate website.", tmp_path), silence_s=0.3)
    c.post("/v1/voice/ptt/stop")
    wait_for(lambda: engine.last_result is not None, timeout=60)
    text = engine.last_result.transcript.lower()
    assert "corporate website" in text, text
    assert _last_task(c)["source"] == "voice"


def test_wake_word_then_command_real(real: Any, audio: FakeAudio, tts: FakeTts,
                                     tmp_path: Path) -> None:
    c, engine = real
    c.patch("/v1/voice/settings", json={"wake_word_enabled": True})
    wait_for(lambda: engine.state.value == "standby", timeout=30)
    feed(audio, synth("Hey Jack.", tmp_path))
    wait_for(lambda: "Yes, I'm listening." in tts.spoken, timeout=60)
    wait_for(lambda: engine.state.value == "listening")
    import time

    time.sleep(0.4)
    feed(audio, synth("Create a professional company logo.", tmp_path))
    wait_for(lambda: engine.last_result is not None, timeout=60)
    assert "logo" in engine.last_result.transcript.lower(), engine.last_result.transcript


def test_inline_wake_command_real(real: Any, audio: FakeAudio, tts: FakeTts,
                                  tmp_path: Path) -> None:
    c, engine = real
    c.patch("/v1/voice/settings", json={"wake_word_enabled": True})
    wait_for(lambda: engine.state.value == "standby", timeout=30)
    feed(audio, synth("Jack, connect to my Ubuntu server.", tmp_path))
    wait_for(lambda: engine.last_result is not None, timeout=60)
    text = engine.last_result.transcript.lower()
    assert "ubuntu server" in text and not text.startswith("jack"), text


def test_ordinary_speech_does_not_wake_real(real: Any, audio: FakeAudio, tts: FakeTts,
                                            tmp_path: Path) -> None:
    c, engine = real
    c.patch("/v1/voice/settings", json={"wake_word_enabled": True})
    wait_for(lambda: engine.state.value == "standby", timeout=30)
    feed(audio, synth("The weather is lovely today, let's go for a walk.", tmp_path))
    import time

    time.sleep(3)
    assert tts.spoken == [] and engine.last_result is None
