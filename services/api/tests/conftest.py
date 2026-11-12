from __future__ import annotations

import os
import secrets
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from jack_api.app import create_app
from jack_api.config import Settings
from jack_api.voice.asr import Transcript
from jack_api.voice.audio import AudioDevice, AudioUnavailable
from jack_api.voice.tts import Voice

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
WS_URL = f"ws://127.0.0.1:{PORT}/v1/ws"


class FakeStream:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeAudio:
    """Simulated PortAudio backend: two microphones; tests push 32 ms frames."""

    def __init__(self) -> None:
        self.available = True
        self.devices = [
            AudioDevice("Windows WASAPI:Headset Mic", "Headset Mic", "Windows WASAPI", 1, True, 1),
            AudioDevice("Windows WASAPI:USB Mic", "USB Mic", "Windows WASAPI", 2, False, 2),
        ]
        self.fail_open: str | None = None
        self.streams: list[FakeStream] = []
        self.opened_with: list[AudioDevice | None] = []
        self._on_frame: Callable[[np.ndarray], None] | None = None

    def status(self) -> tuple[bool, str | None]:
        return (self.available, None if self.available else "PortAudio not available")

    def input_devices(self) -> list[AudioDevice]:
        return list(self.devices) if self.available else []

    def open_stream(self, device: AudioDevice | None,
                    on_frame: Callable[[np.ndarray], None]) -> FakeStream:
        if self.fail_open:
            raise AudioUnavailable(self.fail_open)
        self.opened_with.append(device)
        self._on_frame = on_frame
        stream = FakeStream()
        self.streams.append(stream)
        return stream

    @property
    def open(self) -> bool:
        return bool(self.streams) and not self.streams[-1].closed

    def emit(self, level: float, frames: int = 1) -> None:
        """Push frames whose RMS maps to `level` (0..1 on the -60..0 dBFS scale)."""
        assert self._on_frame is not None
        amp = int(32767 * 10 ** ((level * 60 - 60) / 20)) if level > 0 else 0
        frame = np.full(512, amp, dtype=np.int16)
        frame[::2] = -amp
        for _ in range(frames):
            self._on_frame(frame.copy())

    def speech(self, seconds: float) -> None:
        self.emit(0.8, max(1, int(seconds / 0.032)))

    def silence(self, seconds: float) -> None:
        self.emit(0.0, max(1, int(seconds / 0.032)))


class FakeVad:
    """Speech when the (filtered) frame is loud; deterministic stand-in for Silero."""

    def prob(self, frame: np.ndarray) -> float:
        return 1.0 if float(np.sqrt(np.mean(frame * frame))) > 0.01 else 0.0

    def reset(self) -> None:
        pass


class FakeRecognizer:
    """Scripted ASR. `script[model]` is a list of transcripts returned in order."""

    def __init__(self) -> None:
        self.models = {"tiny.en", "small.en"}
        self.script: dict[str, list[str]] = {"tiny.en": [], "small.en": []}
        self.calls: list[tuple[str, float]] = []
        self.logprob = -0.3

    def available(self, model: str) -> bool:
        return model in self.models

    def transcribe(self, audio: np.ndarray, model: str, *, prompt: str | None = None
                   ) -> Transcript:
        self.calls.append((model, audio.shape[0] / 16000))
        queue = self.script.get(model) or [""]
        text = queue.pop(0) if len(queue) > 1 else queue[0]
        return Transcript(text, self.logprob, 0.05)


class FakeTts:
    engine = "fake"

    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.hold = False  # block until cancelled (to test barge-in)
        self.interrupted = 0

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def voices(self) -> list[Voice]:
        return [Voice("v1", "Test Voice", "en-US"), Voice("v2", "Other Voice", "en-GB")]

    def speak(self, text: str, voice_id: str | None, rate: float,
              cancel: threading.Event) -> bool:
        self.spoken.append(text)
        if self.hold:
            cancel.wait(5)
        if cancel.is_set():
            self.interrupted += 1
            return False
        return True


def wait_for(cond: Callable[[], object], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


@pytest.fixture
def audio() -> FakeAudio:
    return FakeAudio()


@pytest.fixture
def asr() -> FakeRecognizer:
    return FakeRecognizer()


@pytest.fixture
def tts() -> FakeTts:
    return FakeTts()


@pytest.fixture
def token() -> str:
    return secrets.token_hex(32)


@pytest.fixture
def database_url(tmp_path: Path) -> Iterator[str]:
    """SQLite by default; set JACK_TEST_DATABASE_URL to run the suite on PostgreSQL."""
    pg = os.environ.get("JACK_TEST_DATABASE_URL")
    if not pg:
        yield f"sqlite:///{(tmp_path / 'jack.db').as_posix()}"
        return
    schema = f"t_{uuid.uuid4().hex[:12]}"
    admin = create_engine(pg)
    with admin.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    sep = "&" if "?" in pg else "?"
    yield f"{pg}{sep}options=-csearch_path%3D{schema}"
    with admin.begin() as c:
        c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


@pytest.fixture
def settings(tmp_path: Path, token: str, database_url: str) -> Settings:
    return Settings(session_token=token, port=PORT, data_dir=tmp_path / "data",
                    database_url=database_url, ws_auth_timeout_s=0.5,
                    health_interval_s=0.2, metrics_interval_s=0.2)


@pytest.fixture
def client(settings: Settings, token: str, audio: FakeAudio, asr: FakeRecognizer,
           tts: FakeTts) -> Iterator[TestClient]:
    app = create_app(settings, audio_backend=audio, recognizer=asr, tts=tts,
                     vad_factory=FakeVad)
    with TestClient(app, base_url=BASE, headers={"Authorization": f"Bearer {token}"}) as c:
        yield c


@pytest.fixture
def anon(settings: Settings, audio: FakeAudio, asr: FakeRecognizer,
         tts: FakeTts) -> Iterator[TestClient]:
    app = create_app(settings, audio_backend=audio, recognizer=asr, tts=tts,
                     vad_factory=FakeVad)
    with TestClient(app, base_url=BASE) as c:
        yield c
