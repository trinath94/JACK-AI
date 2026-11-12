from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from jack_api.app import create_app
from jack_api.config import Settings

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
WS_URL = f"ws://127.0.0.1:{PORT}/v1/ws"


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
                    health_interval_s=0.2)


@pytest.fixture
def client(settings: Settings, token: str) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app, base_url=BASE, headers={"Authorization": f"Bearer {token}"}) as c:
        yield c


@pytest.fixture
def anon(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app, base_url=BASE) as c:
        yield c
