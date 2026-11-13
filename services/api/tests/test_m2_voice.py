"""Voice capture behaviour introduced in Milestone 2 (still valid with the M3 pipeline):
push-to-talk, device selection, mute/privacy enforcement, watchdogs, settings."""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conftest import WS_URL, FakeAudio, FakeRecognizer, FakeTts, wait_for
from jack_api.voice.audio import level_from_int16


def _engine(client: TestClient) -> Any:
    return client.app.state.svc.voice  # type: ignore[attr-defined]


def _ws(client: TestClient, token: str) -> Any:
    ws = client.websocket_connect(WS_URL)
    conn = ws.__enter__()
    conn.send_json({"type": "auth", "token": token})
    conn.receive_json()  # hello
    conn.receive_json()  # health
    return ws, conn


def _next_topic(conn: Any, topic: str, limit: int = 60) -> dict[str, Any]:
    for _ in range(limit):
        msg = conn.receive_json()
        if msg["topic"] == topic:
            return msg  # type: ignore[no-any-return]
    raise AssertionError(f"{topic} not received")


def test_status_reports_capabilities(client: TestClient) -> None:
    st = client.get("/v1/voice/status").json()
    assert st["state"] == "idle"
    caps = st["capabilities"]
    assert caps["capture"] is True
    assert caps["wake_word"] is True and caps["wake_word_engine"] == "keyword-asr"
    assert caps["speech_recognition"] is True
    assert caps["speech_synthesis"] is True


def test_lists_input_devices(client: TestClient) -> None:
    devices = client.get("/v1/voice/devices").json()
    assert [d["name"] for d in devices] == ["Headset Mic", "USB Mic"]
    assert devices[0]["is_default"] is True


def test_ptt_cycle_streams_level_then_recognises(
        client: TestClient, token: str, audio: FakeAudio, asr: FakeRecognizer) -> None:
    asr.script["small.en"] = ["Build a corporate website."]
    ws, conn = _ws(client, token)
    try:
        st = client.post("/v1/voice/ptt/start", json={"source": "ui"}).json()
        assert st["state"] == "listening"
        audio.speech(0.6)
        assert _next_topic(conn, "voice.level")["data"]["level"] == pytest.approx(0.8, abs=0.02)
        stopped = client.post("/v1/voice/ptt/stop").json()
        assert stopped["processing"] is True and stopped["stopped_by"] == "released"
        utt = _next_topic(conn, "voice.utterance")["data"]
        assert utt["transcribed"] is True
        assert utt["transcript"] == "Build a corporate website"
        assert utt["task_id"]
        # JACK asked a requirements question, so it keeps listening for the answer briefly.
        assert "?" in utt["reply"]
        assert _next_topic(conn, "voice.followup")["data"]["wait_s"] == 0.3
    finally:
        ws.__exit__(None, None, None)
    # No answer: the follow-up ends; with the wake word off the microphone closes.
    wait_for(lambda: audio.streams[-1].closed)
    actions = [a["action"] for a in client.get("/v1/audit").json()["items"]]
    assert "voice.capture.start" in actions and "voice.capture.stop" in actions


def test_level_events_are_throttled(client: TestClient, token: str, audio: FakeAudio) -> None:
    ws, conn = _ws(client, token)
    try:
        client.post("/v1/voice/ptt/start", json={})
        audio.speech(1.6)  # 50 frames in a burst
        time.sleep(0.3)
        client.post("/v1/voice/ptt/stop")
        topics = []
        while True:
            msg = conn.receive_json()
            topics.append(msg["topic"])
            if msg["topic"] == "voice.utterance":
                break
        # Frames are processed faster than real time in this test, so the 15 Hz throttle
        # collapses the burst to a handful of events.
        assert topics.count("voice.level") <= 6
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
    for body in ({"wake_word_sensitivity": 0.95}, {"max_listen_s": 1}, {"bogus": 1},
                 {"asr_model": "large-v3"}, {"tts_rate": 3}, {"history_retention_days": 0}):
        assert client.patch("/v1/voice/settings", json=body).status_code == 422, body


def test_settings_persist_across_restart(settings, token, audio, asr, tts) -> None:  # type: ignore[no-untyped-def]
    from conftest import FakeVad
    from jack_api.app import create_app

    h = {"Authorization": f"Bearer {token}"}

    def app():  # type: ignore[no-untyped-def]
        return create_app(settings, audio, recognizer=asr, tts=tts, vad_factory=FakeVad)

    with TestClient(app(), base_url="http://127.0.0.1:8765", headers=h) as c:
        c.patch("/v1/voice/settings", json={"privacy_mode": True, "wake_word_sensitivity": 0.3,
                                            "asr_model": "base.en", "tts_rate": 1.25})
    with TestClient(app(), base_url="http://127.0.0.1:8765", headers=h) as c:
        st = c.get("/v1/voice/status").json()
        assert st["settings"]["privacy_mode"] is True
        assert st["settings"]["wake_word_sensitivity"] == 0.3
        assert st["settings"]["asr_model"] == "base.en"
        assert st["settings"]["tts_rate"] == 1.25
        assert st["state"] == "disabled"


def test_auto_stop_after_max_duration(client: TestClient, audio: FakeAudio) -> None:
    engine = _engine(client)
    # Bypass validation (min 5 s) to keep the test fast.
    engine._settings = engine.settings.model_copy(update={"max_listen_s": 0.3})
    engine.start_ptt("ui")
    audio.speech(0.1)
    wait_for(lambda: engine.last_result is not None)
    assert engine.last_result.stopped_by == "max_duration"


def test_no_microphone_degrades_health(client: TestClient, audio: FakeAudio) -> None:
    audio.devices = []
    caps = client.get("/v1/voice/status").json()["capabilities"]
    assert caps["capture"] is False and caps["capture_detail"] == "No microphone found"
    assert caps["wake_word"] is False
    voice = next(c for c in client.get("/v1/health").json()["components"] if c["name"] == "voice")
    assert voice["status"] == "degraded"


def test_microphone_delivering_no_audio_is_reported(client: TestClient, audio: FakeAudio) -> None:
    engine = _engine(client)
    engine.no_audio_timeout_s = 0.2
    client.post("/v1/voice/ptt/start", json={})  # fake backend never emits a frame
    wait_for(lambda: engine.state.value == "idle")
    assert engine.last_result.stopped_by == "no_audio"
    assert audio.streams[0].closed
    # The notification is created just after the state changes; wait for it rather than race.
    wait_for(lambda: "No audio from microphone" in
             [n["title"] for n in client.get("/v1/notifications").json()["items"]])


def test_watchdog_quiet_when_audio_flows(client: TestClient, audio: FakeAudio) -> None:
    engine = _engine(client)
    engine.no_audio_timeout_s = 0.2
    client.post("/v1/voice/ptt/start", json={})
    audio.silence(0.1)
    time.sleep(0.4)
    assert engine.state.value == "listening"
    client.post("/v1/voice/ptt/stop")


def test_level_mapping() -> None:
    import numpy as np

    assert level_from_int16(np.array([], dtype=np.int16)) == 0.0
    assert level_from_int16(np.zeros(100, dtype=np.int16)) == 0.0
    assert level_from_int16(np.array([32767, -32767] * 50)) == pytest.approx(1.0, abs=0.01)
    assert level_from_int16(np.array([33, -33] * 50)) < 0.05  # ~ -60 dBFS


def test_tts_fixture_unused_guard(tts: FakeTts) -> None:
    assert tts.engine == "fake"
