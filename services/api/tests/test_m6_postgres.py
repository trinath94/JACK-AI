"""Milestone 6: embedded PostgreSQL (decision D-1) with the real bundled binaries.

PostgreSQL refuses to run as root, so these tests skip there (CI runs them as a normal user,
on Linux and Windows).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from conftest import BASE, FakeAudio, FakeRecognizer, FakeTts, FakeVad
from jack_api import embedded_pg
from jack_api.ai.credentials import MemoryStore
from jack_api.app import create_app
from jack_api.config import Settings
from jack_api.db import Database
from jack_api.embedded_pg import EmbeddedPostgres, PostgresUnavailable

pytestmark = [
    pytest.mark.skipif(embedded_pg.find_binaries() is None, reason="PostgreSQL binaries missing"),
    pytest.mark.skipif(sys.platform != "win32" and os.geteuid() == 0,
                       reason="PostgreSQL refuses to run as root"),
]


class SecureStore(MemoryStore):
    """Stands in for Windows Credential Manager."""

    kind = "test.secure"
    secure = True


@pytest.fixture
def creds() -> SecureStore:
    return SecureStore()


def _settings(tmp_path: Path, token: str, database: str) -> Settings:
    return Settings(session_token=token, port=8765, data_dir=tmp_path / "data",
                    database=database, health_interval_s=0.2)  # type: ignore[arg-type]


def _client(settings: Settings, token: str, creds: Any, audio: FakeAudio, asr: FakeRecognizer,
            tts: FakeTts) -> TestClient:
    app = create_app(settings, audio_backend=audio, recognizer=asr, tts=tts,
                     vad_factory=FakeVad, credentials=creds)
    return TestClient(app, base_url=BASE, headers={"Authorization": f"Bearer {token}"})


# ------------------------------------------------------------------ the server itself
def test_start_stop_restart_and_password_handling(tmp_path: Path, creds: SecureStore) -> None:
    pg = EmbeddedPostgres(tmp_path / "data", creds)
    url = pg.start()
    try:
        assert pg.status().running and "127.0.0.1" in pg.status().detail
        pw = creds.get(embedded_pg.CRED_NAME)
        assert pw and len(pw) >= 32 and pw in url
        assert not (tmp_path / "data" / "pg16.pass").exists()  # secure store: no file
        hba = (pg.cluster / "pg_hba.conf").read_text()
        assert "trust" not in hba and "127.0.0.1/32 scram-sha-256" in hba
        db = Database(url)
        with db.engine.connect() as c:
            assert c.execute(text("show server_version")).scalar().startswith("16.")
            assert c.execute(text("show timezone")).scalar() == "UTC"
            assert c.execute(text("show listen_addresses")).scalar() == "127.0.0.1"
        db.dispose()
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(host="127.0.0.1", port=pg.port, user="jack", password="wrong",
                            dbname="jack", connect_timeout=3)
    finally:
        pg.stop()
    assert not pg.status().running
    again = EmbeddedPostgres(tmp_path / "data", creds)
    again.start()
    try:
        assert again.status().running
    finally:
        again.stop()


def test_a_crashed_server_is_stopped_before_a_new_start(tmp_path: Path,
                                                        creds: SecureStore) -> None:
    first = EmbeddedPostgres(tmp_path / "data", creds)
    first.start()
    old_pid = first._proc.pid if first._proc else None
    # The service died without stopping it: a new instance must take over cleanly.
    second = EmbeddedPostgres(tmp_path / "data", creds)
    try:
        second.start()
        assert second.status().running
        if old_pid is not None:
            assert not embedded_pg._alive(old_pid) or first._proc.poll() is not None  # type: ignore[union-attr]
    finally:
        second.stop()
        first.stop()


def test_missing_password_is_reported_not_guessed(tmp_path: Path, creds: SecureStore) -> None:
    pg = EmbeddedPostgres(tmp_path / "data", creds)
    pg.start()
    pg.stop()
    creds.delete(embedded_pg.CRED_NAME)
    with pytest.raises(PostgresUnavailable, match="password is missing"):
        EmbeddedPostgres(tmp_path / "data", creds).start()


# ------------------------------------------------------------------ the app on PostgreSQL
def test_app_runs_on_embedded_postgres(tmp_path: Path, token: str, creds: SecureStore,
                                       audio: FakeAudio, asr: FakeRecognizer,
                                       tts: FakeTts) -> None:
    settings = _settings(tmp_path, token, "embedded")
    with _client(settings, token, creds, audio, asr, tts) as c:
        db = next(x for x in c.get("/v1/health").json()["components"] if x["name"] == "database")
        assert db["status"] == "healthy" and db["detail"].startswith("PostgreSQL 16")
        r = c.post("/v1/discovery/messages", json={"text": "Build a website"})
        assert r.status_code == 200
        c.patch("/v1/voice/settings", json={"tts_rate": 1.3})
        tid = r.json()["reply"]["task_id"]
    assert (settings.data_dir / "prefs.db").exists()          # preferences: SQLite
    assert not (settings.data_dir / "jack.db").exists()       # everything else: PostgreSQL
    with _client(settings, token, creds, audio, asr, tts) as c:
        assert c.get(f"/v1/tasks/{tid}").json()["status"] == "WAITING_FOR_INFORMATION"
        assert c.get("/v1/voice/status").json()["settings"]["tts_rate"] == 1.3
        assert c.get("/v1/audit/verify").json()["valid"] is True


def test_existing_sqlite_data_moves_to_postgres_once(tmp_path: Path, token: str,
                                                     creds: SecureStore, audio: FakeAudio,
                                                     asr: FakeRecognizer, tts: FakeTts) -> None:
    # An M5 install: everything in SQLite jack.db, preferences included.
    old = _settings(tmp_path, token, "sqlite")
    with _client(old, token, creds, audio, asr, tts) as c:
        r = c.post("/v1/discovery/messages", json={"text": "Build a website"}).json()
        c.post("/v1/discovery/messages",
               json={"text": "My company", "session_id": r["reply"]["session_id"]})
        before = c.get("/v1/audit", params={"limit": 1}).json()["total"]
        tid = r["reply"]["task_id"]
    legacy = Database(f"sqlite:///{(old.data_dir / 'jack.db').as_posix()}")
    with legacy.session() as s:  # the M1–M5 location of preferences
        s.execute(text("insert into settings(key, value, updated_at) values "
                       "('legacy.only', '{\"x\": 1}', '2026-11-01 10:00:00')"))
    legacy.dispose()
    (old.data_dir / "prefs.db").unlink()  # as if prefs.db never existed (pre-M6)

    new = _settings(tmp_path, token, "embedded")
    with _client(new, token, creds, audio, asr, tts) as c:
        health = {x["name"]: x for x in c.get("/v1/health").json()["components"]}
        assert health["database"]["detail"].startswith("PostgreSQL 16")
        t = c.get(f"/v1/tasks/{tid}").json()
        assert t["status"] == "WAITING_FOR_INFORMATION" and len(t["events"]) >= 4
        s = c.get("/v1/discovery/sessions").json()
        assert s and s[0]["task_id"] == tid
        verify = c.get("/v1/audit/verify").json()
        assert verify["valid"] is True and verify["checked"] > before
        items = c.get("/v1/audit", params={"limit": 200}).json()["items"]
        mig = [a for a in items if a["action"] == "database.migrate"]
        assert len(mig) == 1 and mig[0]["details"]["rows"]["tasks"] == 1
    prefs = Database(f"sqlite:///{(old.data_dir / 'prefs.db').as_posix()}")
    with prefs.engine.connect() as pc:  # preferences moved to prefs.db, not PostgreSQL
        raw = pc.execute(text("select value from settings where key='legacy.only'")).scalar()
        assert json.loads(raw) == {"x": 1}
    prefs.dispose()
    backups = list(old.data_dir.glob("jack.db.pre-postgres-*"))
    assert backups and not (old.data_dir / "jack.db").exists()
    # A second start doesn't move anything again.
    with _client(new, token, creds, audio, asr, tts) as c:
        items = c.get("/v1/audit", params={"limit": 200}).json()["items"]
        assert sum(a["action"] == "database.migrate" for a in items) == 1


def test_falls_back_to_sqlite_and_says_why(tmp_path: Path, token: str, creds: SecureStore,
                                           audio: FakeAudio, asr: FakeRecognizer, tts: FakeTts,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedded_pg, "find_binaries", lambda override=None: None)
    with _client(_settings(tmp_path, token, "embedded"), token, creds, audio, asr, tts) as c:
        db = next(x for x in c.get("/v1/health").json()["components"] if x["name"] == "database")
        assert db["status"] == "degraded" and "not bundled" in db["detail"]
        notes = c.get("/v1/notifications").json()["items"]
        assert any("SQLite" in (n["body"] or "") for n in notes)
        assert c.post("/v1/tasks", json={"command_text": "x", "source": "text"}).status_code == 201


@pytest.fixture(autouse=True)
def _no_leftover_servers(tmp_path: Path) -> Iterator[None]:
    yield
    pid = tmp_path / "data" / "pg16" / "postmaster.pid"
    if pid.exists() and sys.platform != "win32":
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid.read_text().splitlines()[0]), 0)
