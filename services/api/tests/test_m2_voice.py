"""Milestone 2: voice interface (push-to-talk capture, settings, mute/privacy enforcement)."""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conftest import WS_URL, FakeAudio
from jack_api.voice.audio import level_from_int16


def _ws_events(client: TestClient, token: str) -> Any:
    ws = client.websocket_connect(WS_URL)
    conn = ws.__enter__()
    conn.send_json({"type": "auth", "token": token})
    conn.receive_json()  # hello
    conn.receive_json()  # health
    return ws, conn


def _next_topic(conn: Any, topic: str, limit: int = 40) -> dict[str, Any]:
    for _ in range(limit):
        msg = conn.receive_json()
        if msg["topic"] == topic:
            return msg  # type: ignore[no-any-return]
    raise AssertionError(f"{topic} not received")


def test_status_reports_honest_capabilities(client: TestClient) -> None:
    st = client.get("/v1/voice/status").json()
    assert st["state"] == "idle"
    caps = st["capabilities"]
    assert caps["capture"] is True
    # Nothing beyond capture exists before Milestone 3, and the API says so.
    assert caps["wake_word"] is False
    assert caps["speech_recognition"] is False
    assert caps["speech_synthesis"] is False
    assert caps["pending_milestone"] == 3


def test_lists_input_devices(client: TestClient) -> None:
    devices = client.get("/v1/voice/devices").json()
    assert [d["name"] for d in devices] == ["Headset Mic", "USB Mic"]
    assert devices[0]["is_default"] is True


def test_ptt_cycle_captures_level_and_discards_audio(
        client: TestClient, token: str, audio: FakeAudio) -> None:
    ws, conn = _ws_events(client, token)
    try:
        st = client.post("/v1/voice/ptt/start", json={"source": "ui"}).json()
        assert st["state"] == "listening"
        assert _next_topic(conn, "voice.state")["data"]["state"] == "listening"
        audio.emit(0.42)
        assert _next_topic(conn, "voice.level")["data"]["level"] == pytest.approx(0.42)

        res = client.post("/v1/voice/ptt/stop").json()
        assert res["transcribed"] is False and res["transcript"] is None
        assert "Milestone 3" in res["detail"]
        assert res["stopped_by"] == "released"
        assert audio.streams[-1].closed is True
        assert _next_topic(conn, "voice.state")["data"]["state"] == "idle"
    finally:
        ws.__exit__(None, None, None)
    actions = [a["action"] for a in client.get("/v1/audit").json()["items"]]
    assert "voice.capture.start" in actions and "voice.capture.stop" in actions


def test_level_events_are_throttled(client: TestClient, token: str, audio: FakeAudio) -> None:
    ws, conn = _ws_events(client, token)
    try:
        client.post("/v1/voice/ptt/start", json={})
        for _ in range(50):
            audio.emit(0.5)  # 50 callbacks in a burst
        client.post("/v1/voice/ptt/stop")
        topics = []
        while True:
            msg = conn.receive_json()
            topics.append(msg["topic"])
            if msg["topic"] == "voice.utterance":
                break
        assert topics.count("voice.level") <= 2
    finally:
        ws.__exit__(None, None, None)


def test_stop_when_not_listening_is_noop(client: TestClient) -> None:
    r = client.post("/v1/voice/ptt/stop")
    assert r.status_code == 200 and r.json() is None


def test_double_start_keeps_single_stream(client: TestClient, audio: FakeAudio) -> None:
    client.post("/v1/voice/ptt/start", json={})
    client.post("/v1/voice/ptt/start", json={})
    assert len(audio.streams) == 1
    client.post("/v1/voice/ptt/stop")


@pytest.mark.parametrize("flag,code", [("muted", "muted"), ("privacy_mode", "privacy_mode")])
def test_mute_and_privacy_block_capture(
        client: TestClient, audio: FakeAudio, flag: str, code: str) -> None:
    assert client.patch("/v1/voice/settings", json={flag: True}).status_code == 200
    assert client.get("/v1/voice/status").json()["state"] == "disabled"
    r = client.post("/v1/voice/ptt/start", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == code
    assert audio.streams == []  # the microphone was never opened


def test_muting_while_listening_closes_microphone(client: TestClient, audio: FakeAudio) -> None:
    client.post("/v1/voice/ptt/start", json={})
    client.patch("/v1/voice/settings", json={"muted": True})
    assert audio.streams[0].closed is True
    assert client.get("/v1/voice/status").json()["state"] == "disabled"
    client.patch("/v1/voice/settings", json={"muted": False})
    assert client.get("/v1/voice/status").json()["state"] == "idle"


def test_selected_device_is_used(client: TestClient, audio: FakeAudio) -> None:
    r = client.patch("/v1/voice/settings", json={"input_device_id": "Windows WASAPI:USB Mic"})
    assert r.status_code == 200
    client.post("/v1/voice/ptt/start", json={})
    client.post("/v1/voice/ptt/stop")
    assert audio.opened_with[-1] is not None and audio.opened_with[-1].name == "USB Mic"


def test_unknown_device_rejected(client: TestClient) -> None:
    r = client.patch("/v1/voice/settings", json={"input_device_id": "MME:Nope"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "unknown_device"


def test_unplugged_device_blocks_capture(client: TestClient, audio: FakeAudio) -> None:
    client.patch("/v1/voice/settings", json={"input_device_id": "Windows WASAPI:USB Mic"})
    audio.devices = audio.devices[:1]  # USB mic unplugged
    r = client.post("/v1/voice/ptt/start", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "unknown_device"


def test_open_failure_reported_and_audited(client: TestClient, audio: FakeAudio) -> None:
    audio.fail_open = "could not open microphone: device busy"
    r = client.post("/v1/voice/ptt/start", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "audio_unavailable"
    audit = client.get("/v1/audit").json()["items"]
    assert any(a["action"] == "voice.capture.start" and a["outcome"] == "error" for a in audit)


def test_settings_validation(client: TestClient) -> None:
    assert client.patch("/v1/voice/settings",
                        json={"wake_word_sensitivity": 0.95}).status_code == 422
    assert client.patch("/v1/voice/settings", json={"max_listen_s": 1}).status_code == 422
    assert client.patch("/v1/voice/settings", json={"bogus": 1}).status_code == 422


def test_settings_persist_across_restart(settings, token, audio) -> None:  # type: ignore[no-untyped-def]
    from jack_api.app import create_app

    h = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app(settings, audio), base_url="http://127.0.0.1:8765", headers=h) as c:
        c.patch("/v1/voice/settings", json={"privacy_mode": True, "wake_word_sensitivity": 0.3})
    with TestClient(create_app(settings, audio), base_url="http://127.0.0.1:8765", headers=h) as c:
        st = c.get("/v1/voice/status").json()
        assert st["settings"]["privacy_mode"] is True
        assert st["settings"]["wake_word_sensitivity"] == 0.3
        assert st["state"] == "disabled"


def test_auto_stop_after_max_duration(client: TestClient, audio: FakeAudio) -> None:
    engine = client.app.state.svc.voice  # type: ignore[attr-defined]
    # Bypass validation (min 5 s) to keep the test fast; drive the engine directly.
    engine._settings = engine.settings.model_copy(update={"max_listen_s": 0.2})
    engine.start_ptt("ui")
    deadline = time.monotonic() + 3
    while engine.state.value == "listening" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert engine.state.value == "idle"
    assert engine.last_result.stopped_by == "max_duration"
    assert audio.streams[0].closed


def test_no_microphone_degrades_health(client: TestClient, audio: FakeAudio) -> None:
    audio.devices = []
    caps = client.get("/v1/voice/status").json()["capabilities"]
    assert caps["capture"] is False and caps["capture_detail"] == "No microphone found"
    voice = next(c for c in client.get("/v1/health").json()["components"] if c["name"] == "voice")
    assert voice["status"] == "degraded"


def test_level_mapping() -> None:
    from array import array

    assert level_from_int16(array("h")) == 0.0
    assert level_from_int16(array("h", [0] * 100)) == 0.0
    assert level_from_int16(array("h", [32767, -32767] * 50)) == pytest.approx(1.0, abs=0.01)
    quiet = level_from_int16(array("h", [33, -33] * 50))  # ~ -60 dBFS
    assert quiet < 0.05
