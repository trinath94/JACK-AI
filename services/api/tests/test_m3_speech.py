"""Milestone 3: speech recognition, wake word, spoken replies, history, model management."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from conftest import FakeAudio, FakeRecognizer, FakeTts, wait_for
from jack_api.voice.asr import ModelManager
from jack_api.voice.dsp import HighPass, Segmenter
from jack_api.voice.wakeword import confidence_ok, split_wake


def _engine(client: TestClient) -> Any:
    return client.app.state.svc.voice  # type: ignore[attr-defined]


def _tasks(client: TestClient) -> list[dict[str, Any]]:
    return client.get("/v1/tasks").json()["items"]  # type: ignore[no-any-return]


def _say_ptt(client: TestClient, audio: FakeAudio, seconds: float = 0.6) -> Any:
    engine = _engine(client)
    engine.last_result = None
    client.post("/v1/voice/ptt/start", json={})
    audio.speech(seconds)
    time.sleep(0.15)
    client.post("/v1/voice/ptt/stop")
    wait_for(lambda: engine.last_result is not None)
    wait_for(lambda: engine.state.value in ("idle", "standby"))
    return engine.last_result


# ------------------------------------------------------------------ push-to-talk → task
def test_spoken_command_becomes_voice_task_and_reply(
        client: TestClient, audio: FakeAudio, asr: FakeRecognizer, tts: FakeTts) -> None:
    asr.script["small.en"] = ["Build a professional corporate website."]
    u = _say_ptt(client, audio)
    assert u.transcript == "Build a professional corporate website"
    task = _tasks(client)[0]
    assert task["id"] == u.task_id and task["source"] == "voice"
    assert task["command_text"] == "Build a professional corporate website"
    assert tts.spoken[-1].startswith("Got it. I've added")
    assert "later version" in tts.spoken[-1]  # honest: no execution yet


def test_ptt_strips_spoken_wake_phrase(client: TestClient, audio: FakeAudio,
                                       asr: FakeRecognizer) -> None:
    asr.script["small.en"] = ["Hey Jack, upgrade my application on GitHub."]
    assert _say_ptt(client, audio).transcript == "upgrade my application on GitHub"


def test_ptt_without_speech_skips_recognition(client: TestClient, audio: FakeAudio,
                                              asr: FakeRecognizer, tts: FakeTts) -> None:
    engine = _engine(client)
    client.post("/v1/voice/ptt/start", json={})
    audio.silence(0.5)
    time.sleep(0.1)
    client.post("/v1/voice/ptt/stop")
    wait_for(lambda: engine.last_result is not None)
    assert engine.last_result.transcribed is False
    assert asr.calls == []
    wait_for(lambda: tts.spoken == ["I didn't hear anything."])


def test_ptt_without_model_says_how_to_fix(client: TestClient, audio: FakeAudio,
                                           asr: FakeRecognizer, tts: FakeTts) -> None:
    asr.models = set()
    u = _say_ptt(client, audio)
    assert u.transcribed is False and u.task_id is None
    assert "Download a speech model" in tts.spoken[-1]
    caps = client.get("/v1/voice/status").json()["capabilities"]
    assert caps["speech_recognition"] is False
    assert "small.en" in caps["speech_recognition_detail"]
    assert _tasks(client) == []


def test_unintelligible_speech(client: TestClient, audio: FakeAudio, asr: FakeRecognizer,
                               tts: FakeTts) -> None:
    asr.script["small.en"] = ["  .  "]
    u = _say_ptt(client, audio)
    assert u.transcript == "" and u.task_id is None
    assert tts.spoken[-1] == "Sorry, I didn't catch that."


def test_selected_asr_model_is_used(client: TestClient, audio: FakeAudio,
                                    asr: FakeRecognizer) -> None:
    asr.models.add("base.en")
    asr.script["base.en"] = ["open my projects"]
    client.patch("/v1/voice/settings", json={"asr_model": "base.en"})
    assert _say_ptt(client, audio).transcript == "open my projects"
    assert asr.calls[-1][0] == "base.en"


def test_spoken_replies_can_be_turned_off(client: TestClient, audio: FakeAudio,
                                          asr: FakeRecognizer, tts: FakeTts) -> None:
    asr.script["small.en"] = ["make a logo"]
    client.patch("/v1/voice/settings", json={"tts_enabled": False})
    _say_ptt(client, audio)
    assert tts.spoken == []


# ------------------------------------------------------------------ wake word
def _enable_wake(client: TestClient, audio: FakeAudio) -> Any:
    engine = _engine(client)
    client.patch("/v1/voice/settings", json={"wake_word_enabled": True})
    wait_for(lambda: engine.state.value == "standby")
    assert audio.open
    return engine


def test_wake_then_command(client: TestClient, audio: FakeAudio, asr: FakeRecognizer,
                           tts: FakeTts) -> None:
    asr.script["tiny.en"] = ["Hey Jack."]
    asr.script["small.en"] = ["Create a professional company logo."]
    engine = _enable_wake(client, audio)
    audio.speech(0.5)
    audio.silence(0.7)
    wait_for(lambda: "Yes, I'm listening." in tts.spoken)
    wait_for(lambda: engine.state.value == "listening")
    time.sleep(0.4)  # echo guard
    audio.speech(1.0)
    audio.silence(1.0)
    wait_for(lambda: engine.last_result is not None)
    u = engine.last_result
    assert u.trigger == "wake" and u.transcript == "Create a professional company logo"
    assert _tasks(client)[0]["source"] == "voice"
    wait_for(lambda: engine.state.value == "standby")  # back to listening for "Jack"
    assert audio.open


def test_wake_with_inline_command(client: TestClient, audio: FakeAudio,
                                  asr: FakeRecognizer, tts: FakeTts) -> None:
    asr.script["tiny.en"] = ["Jack, build a professional corporate"]
    asr.script["small.en"] = ["Jack, build a professional corporate website."]
    engine = _enable_wake(client, audio)
    audio.speech(2.0)
    audio.silence(0.7)
    wait_for(lambda: engine.last_result is not None)
    assert engine.last_result.transcript == "build a professional corporate website"
    assert "Yes, I'm listening." not in tts.spoken  # went straight to the command
    # Biased wake pass, unbiased veto pass, then the command model on the whole utterance.
    assert [m for m, _ in asr.calls] == ["tiny.en", "tiny.en", "small.en"]
    assert asr.prompts[:2] == ["Hey Jack.", None]
    assert asr.calls[0][1] <= 2.5  # wake check only looks at the start of the utterance


def test_other_speech_does_not_wake(client: TestClient, audio: FakeAudio,
                                    asr: FakeRecognizer, tts: FakeTts) -> None:
    asr.script["tiny.en"] = ["I hijacked the meeting agenda, Jack said."]
    engine = _enable_wake(client, audio)
    audio.speech(1.0)
    audio.silence(0.7)
    wait_for(lambda: len(asr.calls) == 1)
    time.sleep(0.2)
    assert tts.spoken == [] and engine.state.value == "standby" and _tasks(client) == []


def test_low_confidence_wake_rejected(client: TestClient, audio: FakeAudio,
                                      asr: FakeRecognizer, tts: FakeTts) -> None:
    asr.script["tiny.en"] = ["Jack"]
    asr.logprob = -3.0
    _enable_wake(client, audio)
    audio.speech(0.5)
    audio.silence(0.7)
    wait_for(lambda: len(asr.calls) == 1)
    time.sleep(0.2)
    assert tts.spoken == []


def test_wake_without_command_times_out(client: TestClient, audio: FakeAudio,
                                        asr: FakeRecognizer, tts: FakeTts) -> None:
    asr.script["tiny.en"] = ["Hey Jack"]
    engine = _enable_wake(client, audio)
    engine.command_wait_s = 0.3
    audio.speech(0.5)
    audio.silence(0.7)
    wait_for(lambda: "I didn't hear a command." in tts.spoken)
    wait_for(lambda: engine.state.value == "standby")


def test_wake_needs_model_and_microphone(client: TestClient, audio: FakeAudio,
                                         asr: FakeRecognizer) -> None:
    asr.models = {"small.en"}
    client.patch("/v1/voice/settings", json={"wake_word_enabled": True})
    st = client.get("/v1/voice/status").json()
    assert st["state"] == "idle" and not audio.open
    assert "tiny.en" in st["capabilities"]["wake_word_detail"]


def test_mute_turns_standby_off(client: TestClient, audio: FakeAudio) -> None:
    _enable_wake(client, audio)
    client.patch("/v1/voice/settings", json={"muted": True})
    assert not audio.open
    assert client.get("/v1/voice/status").json()["state"] == "disabled"
    client.patch("/v1/voice/settings", json={"muted": False})
    wait_for(lambda: audio.open)


def test_wake_events_are_audited(client: TestClient, audio: FakeAudio,
                                 asr: FakeRecognizer, tts: FakeTts) -> None:
    asr.script["tiny.en"] = ["Hey Jack"]
    _enable_wake(client, audio)
    audio.speech(0.5)
    audio.silence(0.7)
    wait_for(lambda: tts.spoken)
    actions = [a["action"] for a in client.get("/v1/audit").json()["items"]]
    assert "voice.standby.start" in actions and "voice.wake" in actions


# ------------------------------------------------------------------ speaking
def test_speaking_is_interruptible_by_push_to_talk(client: TestClient, audio: FakeAudio,
                                                   tts: FakeTts) -> None:
    engine = _engine(client)
    tts.hold = True
    assert client.post("/v1/voice/speak", json={"text": "A long answer"}).status_code == 202
    wait_for(lambda: engine.state.value == "speaking")
    client.post("/v1/voice/ptt/start", json={})  # barge in
    wait_for(lambda: tts.interrupted == 1)
    assert engine.state.value == "listening"
    client.post("/v1/voice/ptt/stop")


def test_stop_speaking(client: TestClient, tts: FakeTts) -> None:
    engine = _engine(client)
    tts.hold = True
    client.post("/v1/voice/speak", json={"text": "Hello"})
    wait_for(lambda: engine.state.value == "speaking")
    assert client.post("/v1/voice/stop-speaking").json() == {"stopped": True}
    wait_for(lambda: engine.state.value == "idle")
    assert client.post("/v1/voice/stop-speaking").json() == {"stopped": False}


def test_jack_does_not_hear_itself(client: TestClient, audio: FakeAudio,
                                   asr: FakeRecognizer, tts: FakeTts) -> None:
    """Half-duplex: audio arriving while JACK speaks never reaches the wake detector."""
    engine = _enable_wake(client, audio)
    tts.hold = True
    client.post("/v1/voice/speak", json={"text": "Hey Jack, this is me talking"})
    wait_for(lambda: engine.state.value == "speaking")
    audio.speech(1.0)
    audio.silence(0.7)
    time.sleep(0.2)
    client.post("/v1/voice/stop-speaking")
    wait_for(lambda: engine.state.value == "standby")
    time.sleep(0.2)
    assert asr.calls == []


def test_voices_and_voice_validation(client: TestClient) -> None:
    assert [v["id"] for v in client.get("/v1/voice/voices").json()] == ["v1", "v2"]
    assert client.patch("/v1/voice/settings", json={"tts_voice_id": "v2"}).status_code == 200
    r = client.patch("/v1/voice/settings", json={"tts_voice_id": "nope"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "unknown_voice"


def test_speak_validation(client: TestClient) -> None:
    assert client.post("/v1/voice/speak", json={"text": ""}).status_code == 422
    assert client.post("/v1/voice/speak", json={"text": "x" * 501}).status_code == 422


# ------------------------------------------------------------------ history
def test_history_records_turns(client: TestClient, audio: FakeAudio,
                               asr: FakeRecognizer) -> None:
    asr.script["small.en"] = ["deploy to staging"]
    u = _say_ptt(client, audio)
    h = client.get("/v1/voice/history").json()
    assert h["total"] == 1
    s = h["items"][0]
    assert s["trigger"] == "ptt" and s["task_id"] == u.task_id
    assert [(t["role"], t["text"]) for t in s["turns"]][0] == ("user", "deploy to staging")
    assert s["turns"][1]["role"] == "jack"


def test_history_off_stores_nothing(client: TestClient, audio: FakeAudio,
                                    asr: FakeRecognizer) -> None:
    asr.script["small.en"] = ["deploy to staging"]
    client.patch("/v1/voice/settings", json={"keep_history": False})
    _say_ptt(client, audio)
    assert client.get("/v1/voice/history").json()["total"] == 0


def test_history_clear_and_retention(client: TestClient, audio: FakeAudio,
                                     asr: FakeRecognizer) -> None:
    asr.script["small.en"] = ["one"]
    _say_ptt(client, audio)
    hist = client.app.state.svc.history  # type: ignore[attr-defined]
    assert hist.purge(older_than_days=1) == 0  # recent sessions are kept
    assert client.delete("/v1/voice/history").json() == {"deleted": 1}
    assert client.get("/v1/voice/history").json()["total"] == 0
    assert any(a["action"] == "voice.history.clear"
               for a in client.get("/v1/audit").json()["items"])


# ------------------------------------------------------------------ model management
def test_model_manager_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[Any] = []
    mm = ModelManager(tmp_path / "models", lambda t, d: events.append((t, d)))
    assert {m["name"]: m["status"] for m in mm.snapshot()} == {
        "tiny.en": "not_downloaded", "base.en": "not_downloaded", "small.en": "not_downloaded"}
    assert mm.available("tiny.en") is False

    def fake_download(repo: str, cache_dir: str, allow_patterns: list[str]) -> str:
        snap = Path(cache_dir) / ("models--" + repo.replace("/", "--")) / "snapshots" / "abc"
        snap.mkdir(parents=True)
        (snap / "model.bin").write_bytes(b"x" * 1000)
        (snap / "config.json").write_text("{}")
        return str(snap)

    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_download)
    assert mm.download("tiny.en") is True
    wait_for(lambda: mm.available("tiny.en"))
    wait_for(lambda: mm.state("tiny.en").status == "ready")
    assert mm.download("tiny.en") is False  # already present
    mm.delete("tiny.en")
    assert mm.state("tiny.en").status == "not_downloaded"
    assert any(t == "voice.models" for t, _ in events)


def test_model_download_failure_is_reported(tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    mm = ModelManager(tmp_path / "models", lambda t, d: None)

    def boom(*_a: Any, **_k: Any) -> str:
        raise OSError("network unreachable")

    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "snapshot_download", boom)
    mm.download("base.en")
    wait_for(lambda: mm.state("base.en").status == "error")
    assert "network unreachable" in (mm.state("base.en").error or "")


def test_model_routes(client: TestClient) -> None:
    names = [m["name"] for m in client.get("/v1/voice/models").json()]
    assert names == ["tiny.en", "base.en", "small.en"]
    assert client.post("/v1/voice/models/large/download").status_code == 404
    assert client.delete("/v1/voice/models/large").status_code == 404


# ------------------------------------------------------------------ units
@pytest.mark.parametrize("text,sens,expected", [
    ("Jack.", 0.5, (True, "")),
    ("Hey Jack, build a website", 0.5, (True, "build a website")),
    ("hey, jack!  open GitHub", 0.5, (True, "open GitHub")),
    ("OK Jack what's the status", 0.5, (True, "what's the status")),
    ("Jak, deploy", 0.5, (True, "deploy")),
    ("Jak, deploy", 0.3, (False, "")),
    ("Jacques, deploy", 0.8, (True, "deploy")),
    ("Jacques, deploy", 0.5, (False, "")),
    ("I hijacked it", 0.9, (False, "")),
    ("Jackson called", 0.9, (False, "")),
    ("tell Jack I'm late", 0.9, (False, "")),
    ("", 0.5, (False, "")),
])
def test_split_wake(text: str, sens: float, expected: tuple[bool, str]) -> None:
    assert split_wake(text, sens) == expected


def test_confidence_gate_tracks_sensitivity() -> None:
    assert confidence_ok(-0.5, 0.1, 0.5)
    assert not confidence_ok(-1.5, 0.1, 0.5)
    assert confidence_ok(-1.5, 0.1, 0.9)
    assert not confidence_ok(-0.5, 0.95, 0.5)


def test_highpass_removes_dc() -> None:
    hp = HighPass()
    dc = np.full(512, 8000, dtype=np.int16)
    out = None
    for _ in range(20):
        out = hp(dc)
    assert out is not None and abs(float(out.mean())) < 0.01


def test_segmenter() -> None:
    seg = Segmenter(end_silence_ms=200, min_speech_ms=100)
    voiced, quiet = np.ones(512, np.float32), np.zeros(512, np.float32)
    assert seg.push(quiet, 0.0) is None
    for _ in range(10):
        assert seg.push(voiced, 0.9) is None
    out = None
    for _ in range(10):
        out = out or seg.push(quiet, 0.0)
    assert out is not None and not out.truncated
    assert 0.3 < out.duration_s < 0.7
    # A single click is not an utterance.
    seg = Segmenter(end_silence_ms=100, start_frames=1, min_speech_ms=250)
    seg.push(voiced, 0.9)
    assert all(seg.push(quiet, 0.0) is None for _ in range(10))


def test_speech_just_after_release_is_kept(client: TestClient, audio: FakeAudio,
                                           asr: FakeRecognizer) -> None:
    """Regression: the last word (still queued, or spoken as the key comes up) must not be
    clipped. Found by the real-model test ("...corporate website" -> "...car")."""
    asr.script["small.en"] = ["open the dashboard"]
    engine = _engine(client)
    client.post("/v1/voice/ptt/start", json={})
    client.post("/v1/voice/ptt/stop")
    audio.speech(0.3)  # arrives within the 250 ms release tail
    wait_for(lambda: engine.last_result is not None)
    assert engine.last_result.transcribed is True
    assert engine.last_result.transcript == "open the dashboard"


def test_tts_failure_is_reported(client: TestClient, audio: FakeAudio, asr: FakeRecognizer,
                                 tts: FakeTts) -> None:
    from jack_api.voice.tts import TtsError

    def broken(*_a: object, **_k: object) -> bool:
        raise TtsError("espeak-ng could not play audio: Unknown PCM default")

    tts.speak = broken  # type: ignore[method-assign]
    asr.script["small.en"] = ["status report"]
    u = _say_ptt(client, audio)
    assert u.task_id  # the command still went through
    assert _engine(client).state.value == "idle"


def test_sound_alike_vetoes_biased_wake(client: TestClient, audio: FakeAudio,
                                        asr: FakeRecognizer, tts: FakeTts) -> None:
    """The biased pass hears "Hey Jack", but the unbiased pass says "Hey Jake": no wake."""
    asr.script["tiny.en"] = ["Hey Jack, how are you?"]
    asr.plain["tiny.en"] = "Hey Jake, how are you?"
    _enable_wake(client, audio)
    audio.speech(0.8)
    audio.silence(0.7)
    wait_for(lambda: len(asr.calls) == 2)
    time.sleep(0.2)
    assert tts.spoken == []


def test_strict_sensitivity_uses_unbiased_pass_only(client: TestClient, audio: FakeAudio,
                                                    asr: FakeRecognizer, tts: FakeTts) -> None:
    asr.script["tiny.en"] = ["Jack."]
    client.patch("/v1/voice/settings", json={"wake_word_sensitivity": 0.3})
    _enable_wake(client, audio)
    audio.speech(0.5)
    audio.silence(0.7)
    wait_for(lambda: tts.spoken)
    assert asr.prompts == [None]


@pytest.mark.parametrize("text,word", [("Hey Jake, how are you", "jake"),
                                       ("Jackson will join", "jackson"),
                                       ("Hey, Zack!", "zack"), ("Hey Jack", None),
                                       ("Doc.", None)])
def test_competing_word(text: str, word: str | None) -> None:
    from jack_api.voice.wakeword import competing_word

    assert competing_word(text) == word
