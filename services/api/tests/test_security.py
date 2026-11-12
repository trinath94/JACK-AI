"""Milestone 1 acceptance items 1–4 and 7 (docs/architecture/ACCEPTANCE_TESTS.md)."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from conftest import WS_URL
from jack_api.config import Settings
from jack_api.redaction import REDACTED, RedactingFilter, redact, register_secret

TOKEN = "a" * 64


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::", "example.com"])  # noqa: S104
def test_refuses_non_loopback_bind(host: str) -> None:
    with pytest.raises(ValidationError):
        Settings(session_token=TOKEN, host=host)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_accepts_loopback_bind(host: str) -> None:
    assert Settings(session_token=TOKEN, host=host).host in {"127.0.0.1", "::1"}


def test_short_token_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(session_token="short")


def test_live_is_public(anon: TestClient) -> None:
    r = anon.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/v1/health", "/v1/tasks", "/v1/audit", "/v1/openapi.json",
                                  "/v1/system/info", "/does-not-exist"])
def test_unauthenticated_requests_rejected_and_audited(
        anon: TestClient, client: TestClient, path: str) -> None:
    r = anon.get(path)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    audit = client.get("/v1/audit").json()["items"]
    denied = [a for a in audit if a["action"] == "api.auth" and a["outcome"] == "denied"]
    assert any(a["target"] == path for a in denied)


def test_wrong_token_rejected(anon: TestClient) -> None:
    r = anon.get("/v1/health", headers={"Authorization": "Bearer " + "b" * 64})
    assert r.status_code == 401


def test_wrong_scheme_rejected(anon: TestClient, token: str) -> None:
    assert anon.get("/v1/health", headers={"Authorization": f"Basic {token}"}).status_code == 401


def test_token_never_in_audit(anon: TestClient, client: TestClient, token: str) -> None:
    anon.get("/v1/tasks", headers={"Authorization": f"Bearer {token[:-1]}x"})
    body = client.get("/v1/audit").text
    assert token not in body and token[:-1] not in body


@pytest.mark.parametrize("host", ["evil.example:8765", "127.0.0.1:9999", "attacker.localhost"])
def test_dns_rebinding_host_rejected(client: TestClient, host: str) -> None:
    r = client.get("/v1/health", headers={"Host": host})
    assert r.status_code == 421
    assert r.json()["error"]["code"] == "forbidden_host"


def test_cors_preflight_only_for_tauri_origin(anon: TestClient) -> None:
    ok = anon.options("/v1/tasks", headers={"Origin": "http://tauri.localhost",
                                            "Access-Control-Request-Method": "POST",
                                            "Access-Control-Request-Headers": "authorization"})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "http://tauri.localhost"
    bad = anon.options("/v1/tasks", headers={"Origin": "https://evil.example",
                                             "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_ws_requires_auth_frame(client: TestClient) -> None:
    with client.websocket_connect(WS_URL) as ws:
        ws.send_json({"type": "auth", "token": "nope"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
    assert exc.value.code == 4401


def test_ws_auth_timeout(client: TestClient) -> None:
    with client.websocket_connect(WS_URL) as ws, pytest.raises(WebSocketDisconnect) as exc:
        ws.receive_text()  # never send auth; server times out after 0.5 s
    assert exc.value.code == 4401


def test_ws_rejects_foreign_origin(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc, client.websocket_connect(
            WS_URL, headers={"Origin": "https://evil.example"}):
        pass
    assert exc.value.code == 4403


def test_ws_authenticated_receives_hello_and_health(client: TestClient, token: str) -> None:
    with client.websocket_connect(WS_URL, headers={"Origin": "http://tauri.localhost"}) as ws:
        ws.send_json({"type": "auth", "token": token})
        hello = ws.receive_json()
        assert hello["topic"] == "hello"
        health = ws.receive_json()
        assert health["topic"] == "health.changed"
        names = {c["name"] for c in health["data"]["components"]}
        assert {"api", "database", "disk"} <= names
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["topic"] == "pong"


@pytest.mark.parametrize("secret", [
    "Bearer abcdefghijklmnop1234",
    "sk-ant-api03-ABCDEFGHIJKLMNOP",
    "ghp_" + "A" * 36,
    "github_pat_" + "B" * 40,
    "password=hunter2hunter2",
    "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----",
])
def test_redaction_patterns(secret: str) -> None:
    out = redact(f"before {secret} after")
    assert REDACTED in out
    assert "before" in out and "after" in out


def test_logging_filter_redacts_registered_secret(caplog: pytest.LogCaptureFixture) -> None:
    secret = "c0ffee" * 10
    register_secret(secret)
    logger = logging.getLogger("jack.test")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="jack.test"):
        logger.info("token is %s", secret)
    assert secret not in caplog.text
    assert REDACTED in caplog.text
