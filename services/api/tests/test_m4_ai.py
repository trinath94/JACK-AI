"""Milestone 4: credentials, Anthropic API provider (against a local fake API over real HTTP),
Claude Code provider (fake CLI), usage and cost tracking, limits, alerts, explicit fallback."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fake_anthropic import FAKE_CLAUDE, VALID_KEY, FakeAnthropic
from fastapi.testclient import TestClient
from pydantic import ValidationError

from conftest import BASE, FakeAudio, FakeRecognizer, FakeTts, FakeVad
from jack_api.ai.credentials import MemoryStore, UnavailableStore, hint
from jack_api.ai.pricing import estimate
from jack_api.app import create_app
from jack_api.config import Settings


@pytest.fixture
def fake() -> Iterator[FakeAnthropic]:
    with FakeAnthropic() as f:
        yield f


@pytest.fixture
def creds() -> MemoryStore:
    return MemoryStore()


def _app(tmp_path: Path, token: str, audio: FakeAudio, asr: FakeRecognizer, tts: FakeTts,
         creds: Any, base_url: str | None = None) -> Any:
    settings = Settings(session_token=token, port=8765, data_dir=tmp_path / "data",
                        anthropic_base_url=base_url, health_interval_s=0.2)
    return create_app(settings, audio, recognizer=asr, tts=tts, vad_factory=FakeVad,
                      credentials=creds)


@pytest.fixture
def ai(tmp_path: Path, token: str, audio: FakeAudio, asr: FakeRecognizer, tts: FakeTts,
       creds: MemoryStore, fake: FakeAnthropic) -> Iterator[TestClient]:
    app = _app(tmp_path, token, audio, asr, tts, creds, fake.base_url)
    with TestClient(app, base_url=BASE, headers={"Authorization": f"Bearer {token}"}) as c:
        c.patch("/v1/ai/settings", json={"anthropic": {"max_retries": 0}})
        yield c


def _keyed(c: TestClient) -> TestClient:
    assert c.put("/v1/ai/anthropic/key", json={"api_key": VALID_KEY}).status_code == 204
    return c


@pytest.fixture
def fake_claude(tmp_path: Path) -> Path:
    if sys.platform == "win32":
        pytest.skip("POSIX shell fake")
    d = tmp_path / "cc"
    d.mkdir()
    exe = d / "claude"
    exe.write_text(FAKE_CLAUDE)
    exe.chmod(0o755)
    return exe


# ------------------------------------------------------------------ credentials
def test_status_before_configuration(ai: TestClient) -> None:
    st = ai.get("/v1/ai/status").json()
    assert st["anthropic"]["configured"] is False and st["anthropic"]["key_hint"] is None
    assert st["anthropic"]["settings"]["model"] == "claude-opus-5-5"
    assert st["credential_store"]["available"] is True
    comp = {c["name"]: c for c in ai.get("/v1/health").json()["components"]}
    assert comp["ai"]["status"] == "degraded"
    assert comp["ai"]["detail"] == "No AI provider configured"


def test_key_is_stored_but_never_returned(ai: TestClient, creds: MemoryStore,
                                          caplog: pytest.LogCaptureFixture) -> None:
    bad = ai.put("/v1/ai/anthropic/key", json={"api_key": "not-a-key-at-all"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_api_key"
    _keyed(ai)
    assert creds.get("anthropic:api_key") == VALID_KEY
    st = ai.get("/v1/ai/status")
    assert st.json()["anthropic"]["key_hint"] == "sk-ant-…TTTT"
    everything = st.text + ai.get("/v1/audit").text + ai.get("/v1/notifications").text
    assert VALID_KEY not in everything
    assert any(a["action"] == "credential.set" for a in ai.get("/v1/audit").json()["items"])
    from jack_api.redaction import RedactingFilter

    logger = logging.getLogger("jack.test.keys")
    logger.addFilter(RedactingFilter())  # installed on every handler by the real entry point
    with caplog.at_level(logging.INFO, logger="jack.test.keys"):
        logger.warning("calling API with key %s", VALID_KEY)
    assert VALID_KEY not in caplog.text and "[REDACTED]" in caplog.text
    assert ai.delete("/v1/ai/anthropic/key").status_code == 204
    assert creds.get("anthropic:api_key") is None


def test_no_secure_store_refuses_to_save(tmp_path: Path, token: str, audio: FakeAudio,
                                         asr: FakeRecognizer, tts: FakeTts) -> None:
    app = _app(tmp_path, token, audio, asr, tts, UnavailableStore("no keyring here"))
    with TestClient(app, base_url=BASE, headers={"Authorization": f"Bearer {token}"}) as c:
        r = c.put("/v1/ai/anthropic/key", json={"api_key": VALID_KEY})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "credential_store_unavailable"
        assert c.get("/v1/ai/status").json()["credential_store"]["available"] is False


def test_hint() -> None:
    assert hint(None) is None
    assert hint("sk-ant-abcdef123456") == "sk-ant-…3456"


# ------------------------------------------------------------------ Anthropic provider
def test_connection_test_records_usage_and_cost(ai: TestClient, fake: FakeAnthropic) -> None:
    _keyed(ai)
    res = ai.post("/v1/ai/anthropic/test").json()
    assert res["ok"] is True and res["reply"] == "OK" and res["model"] == "claude-opus-5-5"
    req = fake.requests[-1]
    assert req["headers"]["authorization"] == f"Bearer {VALID_KEY}"  # JACK's stored key
    assert req["body"]["output_config"] == {"effort": "low"}
    # Refusal fallback is on by default for Opus 5.5 via the server-side beta.
    assert "server-side-fallback-2026-07-01" in req["headers"].get("anthropic-beta", "")
    assert req["body"]["fallbacks"] == "default"
    rec = ai.get("/v1/ai/usage/records").json()["items"][0]
    assert rec["purpose"] == "connection_test" and rec["billing_kind"] == "api"
    assert Decimal(rec["cost_usd"]) == Decimal("0.000148")  # 12×$4/M + 5×$20/M
    assert rec["cost_source"] == "estimated"
    st = ai.get("/v1/ai/status").json()
    assert st["anthropic"]["last_test"]["ok"] is True
    assert st["month"]["api"]["requests"] == 1


def test_wrong_key_reports_auth(ai: TestClient, creds: MemoryStore) -> None:
    creds.set("anthropic:api_key", "sk-ant-api03-" + "W" * 40)
    res = ai.post("/v1/ai/anthropic/test").json()
    assert res["ok"] is False and res["error_code"] == "auth"
    failed = ai.get("/v1/ai/usage/records").json()["items"][0]
    assert failed["succeeded"] is False and failed["error_code"] == "auth"


def test_not_configured(ai: TestClient) -> None:
    r = ai.post("/v1/ai/complete", json={"prompt": "hi"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ai_not_configured"


def test_models_from_api(ai: TestClient) -> None:
    _keyed(ai)
    models = ai.get("/v1/ai/anthropic/models").json()
    assert [m["id"] for m in models] == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-future-9"]
    assert [m["price_known"] for m in models] == [True, True, False]


def test_effort_and_fallback_follow_the_model(ai: TestClient, fake: FakeAnthropic) -> None:
    _keyed(ai)
    ai.patch("/v1/ai/settings", json={"anthropic": {"model": "claude-haiku-4-5"}})
    ai.post("/v1/ai/complete", json={"prompt": "hi"})
    body, headers = fake.requests[-1]["body"], fake.requests[-1]["headers"]
    assert "output_config" not in body and "fallbacks" not in body  # neither supported
    assert "server-side-fallback" not in headers.get("anthropic-beta", "")
    ai.patch("/v1/ai/settings", json={"anthropic": {"model": "claude-sonnet-5-5",
                                                    "effort": "high", "refusal_fallback": False}})
    ai.post("/v1/ai/complete", json={"prompt": "hi"})
    body = fake.requests[-1]["body"]
    assert body["output_config"] == {"effort": "high"} and "fallbacks" not in body


def test_model_fallback_costs_each_model(ai: TestClient, fake: FakeAnthropic) -> None:
    _keyed(ai)
    fake.mode = "fallback"
    out = ai.post("/v1/ai/complete", json={"prompt": "hi"}).json()
    assert out["model_served"] == "claude-opus-4-8"
    assert out["fallbacks"] == [["claude-opus-5-5", "claude-opus-4-8"]]
    recs = ai.get("/v1/ai/usage/records").json()["items"]
    by_model = {r["model"]: Decimal(r["cost_usd"]) for r in recs}
    assert by_model["claude-opus-5-5"] == Decimal("0.000600")  # 100×4 + 10×20 per M
    assert by_model["claude-opus-4-8"] == Decimal("0.001750")  # 100×5 + 50×25 per M
    assert Decimal(out["cost_usd"]) == Decimal("0.002350")
    assert any(a["action"] == "ai.model_fallback" for a in ai.get("/v1/audit").json()["items"])


def test_refusal_is_reported(ai: TestClient, fake: FakeAnthropic) -> None:
    _keyed(ai)
    fake.mode = "refusal"
    out = ai.post("/v1/ai/complete", json={"prompt": "hi"}).json()
    assert out["stop_reason"] == "refusal" and out["refusal_category"] == "cyber"
    assert any(a["action"] == "ai.refusal" for a in ai.get("/v1/audit").json()["items"])


@pytest.mark.parametrize("mode,status,code", [("rate_limit", 429, "ai_rate_limited"),
                                              ("server_error", 502, "ai_server")])
def test_api_errors(ai: TestClient, fake: FakeAnthropic, mode: str, status: int,
                    code: str) -> None:
    _keyed(ai)
    fake.mode = mode
    r = ai.post("/v1/ai/complete", json={"prompt": "hi"})
    assert r.status_code == status and r.json()["error"]["code"] == code
    st = ai.get("/v1/ai/status").json()["month"]["api"]
    assert st["failed"] == 1 and st["requests"] == 0


# ------------------------------------------------------------------ limits & alerts
def test_monthly_limit_alerts_then_blocks(ai: TestClient, fake: FakeAnthropic) -> None:
    _keyed(ai)
    fake.usage = {"input_tokens": 1_000_000, "output_tokens": 0}  # $4.00 per call on Opus 5.5
    ai.patch("/v1/ai/settings", json={"limits": {"monthly_usd": "10"}})
    ai.post("/v1/ai/complete", json={"prompt": "1"})  # $4 = 40%
    assert not [n for n in _notes(ai) if n["kind"] == "ai.spend_alert"]
    ai.post("/v1/ai/complete", json={"prompt": "2"})  # $8 = 80% -> one alert (80)
    alerts = [n["title"] for n in _notes(ai) if n["kind"] == "ai.spend_alert"]
    assert alerts == ["AI spending at 80% of the monthly limit"]
    ai.post("/v1/ai/complete", json={"prompt": "3"})  # $12 = 120%
    r = ai.post("/v1/ai/complete", json={"prompt": "4"})
    assert r.status_code == 402 and r.json()["error"]["code"] == "ai_budget"
    assert len(fake.requests) == 3  # the 4th call never reached the API
    titles = [n["title"] for n in _notes(ai)]
    assert "AI spending at 100% of the monthly limit" in titles
    assert "AI request blocked: monthly spending limit" in titles
    month = ai.get("/v1/ai/usage").json()
    assert month["api"]["cost_usd"] == "12.000000" and month["limit_used_pct"] == 120.0
    assert any(a["action"] == "ai.limit.block" and a["outcome"] == "denied"
               for a in ai.get("/v1/audit").json()["items"])


def test_per_task_limit(ai: TestClient, fake: FakeAnthropic) -> None:
    _keyed(ai)
    tid = ai.post("/v1/tasks", json={"command_text": "research"}).json()["id"]
    fake.usage = {"input_tokens": 500_000, "output_tokens": 0}  # $2 per call
    ai.patch("/v1/ai/settings", json={"limits": {"per_task_usd": "3"}})
    assert ai.post("/v1/ai/complete", json={"prompt": "a", "task_id": tid}).status_code == 200
    assert ai.post("/v1/ai/complete", json={"prompt": "b", "task_id": tid}).status_code == 200
    r = ai.post("/v1/ai/complete", json={"prompt": "c", "task_id": tid})
    assert r.status_code == 402
    assert ai.post("/v1/ai/complete", json={"prompt": "other task"}).status_code == 200


def _notes(c: TestClient) -> list[dict[str, Any]]:
    return c.get("/v1/notifications").json()["items"]  # type: ignore[no-any-return]


# ------------------------------------------------------------------ Claude Code
def test_claude_code_detect_and_complete(ai: TestClient, fake_claude: Path) -> None:
    ai.patch("/v1/ai/settings", json={"claude_code": {"enabled": True,
                                                      "binary": str(fake_claude)}})
    det = ai.post("/v1/ai/claude-code/detect").json()
    assert det["installed"] and det["logged_in"] and det["auth_method"] == "claude.ai"
    assert det["version"].startswith("2.1.322")
    out = ai.post("/v1/ai/complete", json={"prompt": "Say hello", "provider": "claude_code"}).json()
    assert out["text"] == "Hello from Claude Code" and out["billing_kind"] == "claude_code"
    assert out["reported_cost_usd"] == "0.0421"
    log = (fake_claude.parent / "calls.log").read_text()
    assert "STDIN: Say hello" in log  # prompt on stdin, not argv
    assert "Say hello" not in [line for line in log.splitlines() if line.startswith("ARGS")][-1]
    assert "LEAK" not in log  # JACK's session token never reaches the CLI
    assert "--max-turns 1" in log and "CWD_FILES: 0" in log  # one turn, empty folder
    month = ai.get("/v1/ai/usage").json()
    assert month["claude_code"]["requests"] == 1
    assert month["claude_code"]["cost_usd"] == "0.042100"
    assert month["api"]["cost_usd"] == "0"  # never mixed into API spend


def test_claude_code_off_by_default(ai: TestClient) -> None:
    r = ai.post("/v1/ai/complete", json={"prompt": "x", "provider": "claude_code"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ai_not_configured"


def test_claude_code_missing(ai: TestClient, tmp_path: Path) -> None:
    ai.patch("/v1/ai/settings", json={"claude_code": {"binary": str(tmp_path / "nope")}})
    assert ai.post("/v1/ai/claude-code/detect").json()["installed"] is False


# ------------------------------------------------------------------ provider fallback
def test_provider_fallback_only_when_enabled(ai: TestClient, fake: FakeAnthropic,
                                             fake_claude: Path) -> None:
    _keyed(ai)
    fake.mode = "server_error"
    ai.patch("/v1/ai/settings", json={"claude_code": {"enabled": True,
                                                      "binary": str(fake_claude)}})
    assert ai.post("/v1/ai/complete", json={"prompt": "x"}).status_code == 502  # off: no switch
    ai.patch("/v1/ai/settings", json={"fallback": {"enabled": True}})
    out = ai.post("/v1/ai/complete", json={"prompt": "x"})
    assert out.status_code == 200 and out.json()["provider"] == "claude_code"
    assert any(n["kind"] == "ai.fallback" for n in _notes(ai))
    assert any(a["action"] == "ai.fallback" for a in ai.get("/v1/audit").json()["items"])


# ------------------------------------------------------------------ settings & units
def test_settings_validation_and_persistence(tmp_path: Path, token: str, audio: FakeAudio,
                                             asr: FakeRecognizer, tts: FakeTts,
                                             creds: MemoryStore) -> None:
    h = {"Authorization": f"Bearer {token}"}
    with TestClient(_app(tmp_path, token, audio, asr, tts, creds), base_url=BASE,
                    headers=h) as c:
        bad_effort = c.patch("/v1/ai/settings", json={"anthropic": {"effort": "turbo"}})
        assert bad_effort.status_code == 422
        assert c.patch("/v1/ai/settings", json={"limits": {"monthly_usd": "-1"}}).status_code == 422
        assert c.patch("/v1/ai/settings", json={"bogus": {}}).status_code == 422
        c.patch("/v1/ai/settings", json={"anthropic": {"model": "claude-sonnet-5-5"},
                                         "limits": {"monthly_usd": "25"}})
    with TestClient(_app(tmp_path, token, audio, asr, tts, creds), base_url=BASE,
                    headers=h) as c:
        st = c.get("/v1/ai/status").json()
        assert st["anthropic"]["settings"]["model"] == "claude-sonnet-5-5"
        assert st["limits"]["monthly_usd"] == "25"


def test_base_url_override_is_loopback_only() -> None:
    with pytest.raises(ValidationError):
        Settings(session_token="x" * 64, anthropic_base_url="https://evil.example")
    Settings(session_token="x" * 64, anthropic_base_url="http://127.0.0.1:9999")


def test_pricing() -> None:
    assert estimate("claude-opus-5-5", 1_000_000, 1_000_000) == Decimal("24")
    assert estimate("claude-sonnet-5-5", 0, 0, cache_read=1_000_000) == Decimal("0.1")
    # 5-minute cache writes cost 1.25x input, 1-hour 2x
    assert estimate("claude-opus-5-5", 0, 0, cache_write_5m=1_000_000) == Decimal("5")
    assert estimate("claude-opus-5-5", 0, 0, cache_write_1h=1_000_000) == Decimal("8")
    # Haiku 5.5's long-prompt tier
    assert estimate("claude-haiku-5-5", 100_000, 0) == Decimal("0.01")
    assert estimate("claude-haiku-5-5", 200_000, 0) == Decimal("0.1")
    assert estimate("claude-future-9", 1, 1) is None  # never guessed


def test_routes_require_auth(anon: TestClient) -> None:
    for method, path in [("get", "/v1/ai/status"), ("put", "/v1/ai/anthropic/key"),
                         ("post", "/v1/ai/complete"), ("get", "/v1/ai/usage")]:
        assert getattr(anon, method)(path).status_code == 401


def test_json_shapes_are_serialisable(ai: TestClient) -> None:
    json.dumps(ai.get("/v1/ai/status").json())
