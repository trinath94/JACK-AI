from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from jack_api.app import create_app
from jack_api.config import Settings
from jack_api.voice.audio import AudioDevice, AudioUnavailable

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
WS_URL = f"ws://127.0.0.1:{PORT}/v1/ws"


class FakeStream:
    def __init__(self, backend: FakeAudio) -> None:
        self.closed = False
        self._backend = backend

    def close(self) -> None:
        self.closed = True


class FakeAudio:
    """Simulated PortAudio backend: two microphones; tests push levels via `emit`."""

    def __init__(self) -> None:
        self.available = True
        self.devices = [
            AudioDevice("Windows WASAPI:Headset Mic", "Headset Mic", "Windows WASAPI", 1, True, 1),
            AudioDevice("Windows WASAPI:USB Mic", "USB Mic", "Windows WASAPI", 2, False, 2),
        ]
        self.fail_open: str | None = None
        self.streams: list[FakeStream] = []
        self.opened_with: list[AudioDevice | None] = []
        self._on_level: Callable[[float], None] | None = None

    def status(self) -> tuple[bool, str | None]:
        return (self.available, None if self.available else "PortAudio not available")

    def input_devices(self) -> list[AudioDevice]:
        return list(self.devices) if self.available else []

    def open_level_stream(self, device: AudioDevice | None,
                          on_level: Callable[[float], None]) -> FakeStream:
        if self.fail_open:
            raise AudioUnavailable(self.fail_open)
        self.opened_with.append(device)
        self._on_level = on_level
        stream = FakeStream(self)
        self.streams.append(stream)
        return stream

    def emit(self, level: float) -> None:
        assert self._on_level is not None
        self._on_level(level)


@pytest.fixture
def audio() -> FakeAudio:
    return FakeAudio()


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
def client(settings: Settings, token: str, audio: FakeAudio) -> Iterator[TestClient]:
    app = create_app(settings, audio_backend=audio)
    with TestClient(app, base_url=BASE, headers={"Authorization": f"Bearer {token}"}) as c:
        yield c


@pytest.fixture
def anon(settings: Settings, audio: FakeAudio) -> Iterator[TestClient]:
    app = create_app(settings, audio_backend=audio)
    with TestClient(app, base_url=BASE) as c:
        yield c
