"""Service configuration.

All values come from environment variables prefixed ``JACK_``. The Rust supervisor sets
``JACK_SESSION_TOKEN`` and ``JACK_PORT`` in the child environment on every launch.
"""

from __future__ import annotations

import ipaddress
import os
import sys
from functools import cached_property
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "JACK AI"
VERSION = "0.1.0"

# Origins the desktop WebView uses. Tauri 2 serves the UI from `tauri://localhost` on
# macOS/Linux and `http(s)://tauri.localhost` on Windows.
TAURI_ORIGINS = (
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
)
DEV_ORIGINS = ("http://localhost:1420", "http://127.0.0.1:1420")


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME / "data"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME / "data"
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / "jack-ai" / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JACK_", extra="ignore")

    session_token: SecretStr = Field(min_length=32)
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    data_dir: Path = Field(default_factory=default_data_dir)
    database_url: str | None = None
    dev_mode: bool = False
    ws_auth_timeout_s: float = 5.0
    health_interval_s: float = 10.0
    log_level: str = "INFO"

    @field_validator("host")
    @classmethod
    def host_must_be_loopback(cls, v: str) -> str:
        # The local service must never be reachable from the network (threat T5).
        if v == "localhost":
            return "127.0.0.1"
        try:
            ip = ipaddress.ip_address(v)
        except ValueError as exc:
            raise ValueError(f"host must be a loopback IP address, got {v!r}") from exc
        if not ip.is_loopback:
            raise ValueError(f"host must be a loopback address, got {v!r}")
        return v

    @cached_property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'jack.db').as_posix()}"

    @cached_property
    def allowed_origins(self) -> tuple[str, ...]:
        return TAURI_ORIGINS + (DEV_ORIGINS if self.dev_mode else ())

    @cached_property
    def allowed_hosts(self) -> frozenset[str]:
        return frozenset({f"127.0.0.1:{self.port}", f"localhost:{self.port}"})
