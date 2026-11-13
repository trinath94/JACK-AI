"""Milestone 5: requirement discovery (Section 6)."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fake_anthropic import VALID_KEY, FakeAnthropic
from fastapi.testclient import TestClient

from conftest import BASE, FakeAudio, FakeRecognizer, FakeTts, FakeVad, wait_for
from jack_api.ai.credentials import MemoryStore
from jack_api.app import create_app
from jack_api.config import Settings
from jack_api.discovery import rules
from jack_api.discovery.catalog import CATEGORIES, DEFAULT_PHRASES


def say(c: TestClient, text: str, session_id: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"text": text}
    if session_id:
        body["session_id"] = session_id
    r = c.post("/v1/discovery/messages", json=body)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def task(c: TestClient, task_id: str) -> dict[str, Any]:
    return c.get(f"/v1/tasks/{task_id}").json()  # type: ignore[no-any-return]


def timeline(c: TestClient, task_id: str) -> list[str]:
    return [e["to_status"] for e in task(c, task_id)["events"]]


def actions(c: TestClient) -> list[str]:
    return [a["action"] for a in c.get("/v1/audit", params={"limit": 200}).json()["items"]]


# ------------------------------------------------------------------ the spec's example dialogue
def test_website_conversation_follows_the_spec_example(client: TestClient) -> None:
    r = say(client, "Jack, build a professional website.")
    sid, tid = r["reply"]["session_id"], r["reply"]["task_id"]
    assert r["reply"]["text"].startswith("Certainly. I'll handle the development")
    assert "What is the website for?" in r["reply"]["text"]
    assert r["reply"]["expects_answer"] and r["reply"]["slot"] == "purpose"
    assert "My company or business" in r["reply"]["options"]
    assert task(client, tid)["status"] == "WAITING_FOR_INFORMATION"

    r = say(client, "My company.", sid)
    assert r["reply"]["text"] == ("Would you like a corporate website, a customer portal or a "
                                  "full business platform?")
    r = say(client, "A corporate website", sid)
    assert r["reply"]["text"] == "What's the business called?"
    r = say(client, "It's called Acme Holdings", sid)
    assert r["reply"]["slot"] == "features"
    r = say(client, "A contact form and a blog, please", sid)
    assert r["reply"]["slot"] == "branding"
    r = say(client, "Please design them for me", sid)
    assert r["reply"]["slot"] == "hosting"
    r = say(client, "On my own server", sid)

    # Every essential question was asked exactly once, in order, and answers were remembered.
    jack = [t["text"] for t in r["session"]["turns"] if t["role"] == "jack"]
    assert len(jack) == 7 and len(set(jack)) == 7
    s = r["session"]
    assert s["status"] == "awaiting_approval"
    spec = s["spec"]
    assert spec["title"] == "Corporate website for Acme Holdings"
    got = {i["slot"]: i["value"] for i in spec["requirements"]}
    assert got == {"purpose": "company", "site_type": "corporate", "business_name": "Acme Holdings",
                   "features": ["contact_form", "blog"], "branding": "design",
                   "hosting": "own_server"}
    # Everything not asked is a visible, changeable assumption with a sensible default.
    assumed = {i["slot"]: i["value"] for i in spec["assumptions"]}
    assert assumed == {"pages": ["home", "about", "services", "contact"], "style": "modern",
                       "domain": "have"}
    assert spec["scope"]["scale"] == "medium" and spec["approval_required"]
    assert "Form handling" in spec["scope"]["components"]
    names = [i["name"] for i in spec["integrations"]]
    assert "E-mail service" in names and "SSH access to your Ubuntu server" in names
    assert spec["hosting"]["choice"] == "own_server"
    deps = {d["capability"]: d["milestone"] for d in spec["dependencies"]}
    assert deps["Autonomous development with Claude Code"] == 11
    assert deps["Staging and production deployment"] == 13
    assert all(not d["available"] for d in spec["dependencies"])  # honest: not built yet
    assert spec["engines"] == ["local"]
    assert task(client, tid)["status"] == "WAITING_FOR_APPROVAL"
    assert task(client, tid)["title"] == "Corporate website for Acme Holdings"

    r = say(client, "Yes, go ahead", sid)
    assert r["session"]["status"] == "ready" and r["session"]["approved_at"]
    assert "later version" in r["reply"]["text"]  # no pretending to start work
    assert timeline(client, tid) == [
        "RECEIVED", "UNDERSTANDING", "REQUIREMENTS", "WAITING_FOR_INFORMATION",
        "REQUIREMENTS", "WAITING_FOR_APPROVAL", "REQUIREMENTS", "PLANNING"]
    acts = actions(client)
    for a in ("requirements.start", "requirements.spec", "requirements.approve"):
        assert a in acts


def test_facts_in_the_opening_command_are_not_asked_again(client: TestClient) -> None:
    r = say(client, "Jack, build a professional corporate website with online booking")
    assert r["reply"]["slot"] == "business_name"   # purpose and kind of site already known
    answers = {a["slot"]: a for a in r["session"]["answers"]}
    assert answers["purpose"]["value"] == "company"
    assert answers["site_type"]["source"] == "inferred"
    assert answers["features"]["value"] == ["booking"]
    r = say(client, "Northwind", r["reply"]["session_id"])
    assert r["reply"]["slot"] == "branding"  # features came from the command: not asked


# ------------------------------------------------------------------ small jobs, defaults, retries
def test_small_job_skips_approval(client: TestClient) -> None:
    r = say(client, "Research the best note-taking apps for a small team")
    sid, tid = r["reply"]["session_id"], r["reply"]["task_id"]
    assert r["session"]["category"] == "research"
    assert r["reply"]["slot"] == "question"
    r = say(client, "Which note-taking app suits a team of five on Windows", sid)
    r = say(client, "A quick answer", sid)
    s = r["session"]
    assert s["status"] == "ready" and not s["spec"]["approval_required"]
    assert s["spec"]["scope"]["scale"] == "small"
    assert not r["reply"]["expects_answer"]
    assert "later version" in r["reply"]["text"]
    assert task(client, tid)["status"] == "PLANNING"
    assert "WAITING_FOR_APPROVAL" not in timeline(client, tid)


def test_approval_can_be_required_for_every_job(client: TestClient) -> None:
    assert client.patch("/v1/discovery/settings",
                        json={"approval": "always"}).json()["approval"] == "always"
    r = say(client, "Write a README for my project")
    sid = r["reply"]["session_id"]
    r = say(client, "How to install and run the project", sid)
    r = say(client, "Developers", sid)
    assert r["session"]["status"] == "awaiting_approval"


def test_you_decide_and_use_defaults(client: TestClient) -> None:
    r = say(client, "Build an Android app")
    sid = r["reply"]["session_id"]
    assert "you decide" in r["reply"]["text"]  # the hint is given once
    r = say(client, "A habit tracker", sid)
    assert "you decide" not in r["reply"]["text"]
    r = say(client, "you decide", sid)          # platforms -> default
    answers = {a["slot"]: a for a in r["session"]["answers"]}
    assert answers["platforms"]["value"] == "only" and answers["platforms"]["source"] == "default"
    r = say(client, "Use defaults for the rest", sid)
    s = r["session"]
    assert s["status"] == "awaiting_approval" or s["status"] == "ready"
    assumed = {i["slot"] for i in s["spec"]["assumptions"]}
    assert {"backend", "features", "publish"} <= assumed
    assert "You asked me to use defaults for the remaining questions." in s["spec"]["notes"]


def test_unclear_answer_is_asked_again_then_defaulted(client: TestClient) -> None:
    r = say(client, "Build a website")
    sid = r["reply"]["session_id"]
    r = say(client, "hmm, purple", sid)  # matches no option; purpose keeps free text
    assert r["reply"]["slot"] != "purpose"  # allow_other: kept in the user's words
    r = say(client, "elephant", sid) if r["reply"]["slot"] == "business_name" else r
    # Branding is a strict choice: one retry with the options read out, then the default.
    while r["reply"]["slot"] != "branding":
        r = say(client, "you decide", sid)
    r = say(client, "elephant", sid)
    assert r["reply"]["text"].startswith("Sorry, I didn't catch that. You can say")
    assert r["reply"]["slot"] == "branding"
    r = say(client, "giraffe", sid)
    assert r["reply"]["text"].startswith("I'll use the usual choice for that.")
    answers = {a["slot"]: a for a in r["session"]["answers"]}
    assert answers["branding"]["source"] == "default"
    assert answers["purpose"]["display"] == "hmm, purple"


# ------------------------------------------------------------------ conflicts
def test_conflicting_requirements_are_detected_and_resolved(client: TestClient) -> None:
    r = say(client, "Build an online shop website")
    sid = r["reply"]["session_id"]
    while r["reply"]["slot"] not in ("features", None):
        r = say(client, "Bakehouse" if r["reply"]["slot"] == "business_name" else "you decide",
                sid)
    r = say(client, "online payments and a contact form", sid)
    while r["reply"]["slot"] != "hosting":
        r = say(client, "you decide", sid)
    r = say(client, "only on this PC", sid)
    assert r["session"]["status"] == "resolving_conflict"
    assert r["reply"]["text"].startswith("A site that only runs on this PC can't take payments")
    assert r["reply"]["options"] == ["Keep it on this PC, without payments",
                                     "Put it online, with payments"]
    r = say(client, "put it online", sid)
    answers = {a["slot"]: a["value"] for a in r["session"]["answers"]}
    assert answers["hosting"] == "own_server"
    assert "payments" in answers["features"]
    assert r["session"]["status"] == "awaiting_approval"


def test_conflict_resolution_can_drop_a_feature(client: TestClient) -> None:
    r = say(client, "Build a web application")
    sid = r["reply"]["session_id"]
    r = say(client, "Track equipment loans", sid)
    r = say(client, "my own team", sid)
    assert r["reply"]["slot"] == "features"
    r = say(client, "an admin dashboard and reports", sid)
    r = client.put(f"/v1/discovery/sessions/{sid}/answers/auth", json={"value": "none"}).json()
    assert r["session"]["status"] == "resolving_conflict"
    r = say(client, "the first one", sid)  # no sign-in, drop the admin dashboard
    answers = {a["slot"]: a["value"] for a in r["session"]["answers"]}
    assert answers["features"] == ["reports"] and answers["auth"] == "none"


# ------------------------------------------------------------------ category, cancel, blocking
def test_unclear_request_asks_for_the_category(client: TestClient) -> None:
    r = say(client, "Build an app")
    sid = r["reply"]["session_id"]
    assert r["session"]["status"] == "choosing_category"
    assert r["reply"]["text"].startswith("What kind of job is this:")
    assert "Web application" in r["reply"]["options"]
    r = say(client, "a web application", sid)
    assert r["session"]["category"] == "web_app"
    assert r["session"]["category_source"] == "user"
    assert r["reply"]["slot"] == "problem"


def test_non_work_request_can_be_cancelled(client: TestClient) -> None:
    r = say(client, "What's the weather like?")
    sid, tid = r["reply"]["session_id"], r["reply"]["task_id"]
    assert r["session"]["status"] == "choosing_category"
    r = say(client, "never mind", sid)
    assert r["session"]["status"] == "cancelled"
    assert task(client, tid)["status"] == "CANCELLED"
    assert client.post("/v1/discovery/messages",
                       json={"text": "hello", "session_id": sid}).status_code == 409


def test_security_audit_requires_authorisation(client: TestClient) -> None:
    r = say(client, "Run a security audit")
    sid, tid = r["reply"]["session_id"], r["reply"]["task_id"]
    r = say(client, "our website", sid)
    r = say(client, "example.org", sid)
    assert r["reply"]["slot"] == "authorised"
    r = say(client, "no, it's a competitor's site", sid)
    assert r["session"]["status"] == "blocked"
    assert "written permission" in r["reply"]["text"]
    assert task(client, tid)["status"] == "CANCELLED"
    audit = client.get("/v1/audit", params={"limit": 50}).json()["items"]
    blocked = [a for a in audit if a["action"] == "requirements.blocked"]
    assert blocked and blocked[0]["outcome"] == "denied"


# ------------------------------------------------------------------ review, edits, task routes
def test_review_changes_and_ui_edits(client: TestClient) -> None:
    r = say(client, "Build a CRM")
    sid, tid = r["reply"]["session_id"], r["reply"]["task_id"]
    assert client.get(f"/v1/tasks/{tid}/spec").status_code == 404  # nothing yet
    r = say(client, "Contoso, a plumbing company", sid)
    r = say(client, "contacts, sales pipeline and quotes", sid)
    while r["session"]["status"] != "awaiting_approval":
        r = say(client, "you decide", sid)
    # Change something by voice at review time.
    r = say(client, "No, we need single sign-on with Microsoft", sid)
    answers = {a["slot"]: a for a in r["session"]["answers"]}
    assert answers["auth"]["value"] == "sso" and answers["auth"]["source"] == "user"
    assert r["reply"]["text"].startswith("Updated.")
    assert r["session"]["status"] == "awaiting_approval"
    # Edit from the Requirements page; invalid values are rejected.
    bad = client.put(f"/v1/discovery/sessions/{sid}/answers/modules", json={"value": ["golf"]})
    assert bad.status_code == 400
    assert client.put(f"/v1/discovery/sessions/{sid}/answers/nope",
                      json={"value": "x"}).status_code == 400
    ok = client.put(f"/v1/discovery/sessions/{sid}/answers/modules",
                    json={"value": ["contacts", "reports"]}).json()
    assert ok["session"]["status"] == "awaiting_approval"
    spec = client.get(f"/v1/tasks/{tid}/spec").json()["spec"]
    assert "Reporting" in spec["scope"]["components"]
    assert "requirements.edit" in actions(client)
    r = client.post(f"/v1/tasks/{tid}/spec/approve").json()
    assert r["session"]["status"] == "ready"
    assert task(client, tid)["status"] == "PLANNING"
    assert client.post(f"/v1/tasks/{tid}/spec/approve").status_code == 409


def test_task_answers_route_and_active_session(client: TestClient) -> None:
    r = say(client, "Automate my weekly sales report")
    tid = r["reply"]["task_id"]
    active = client.get("/v1/discovery/sessions", params={"active": True}).json()
    assert [s["task_id"] for s in active] == [tid]
    r = client.post(f"/v1/tasks/{tid}/answers",
                    json={"text": "Export sales from the CRM and e-mail a summary"}).json()
    # "weekly" in the command already answered when it runs.
    assert {a["slot"]: a["value"] for a in r["session"]["answers"]}["trigger"] == "schedule"
    assert r["reply"]["slot"] == "systems"
    assert client.post("/v1/tasks/missing/answers", json={"text": "x"}).status_code == 404


def test_a_new_typed_command_starts_a_new_session(client: TestClient) -> None:
    first = say(client, "Build a website")
    second = say(client, "Create a logo for my bakery")
    assert first["reply"]["task_id"] != second["reply"]["task_id"]
    assert second["session"]["category"] == "image_generation"


def test_sessions_survive_a_restart(settings: Settings, token: str, audio: FakeAudio,
                                    asr: FakeRecognizer, tts: FakeTts) -> None:
    def app() -> Any:
        return create_app(settings, audio_backend=audio, recognizer=asr, tts=tts,
                          vad_factory=FakeVad)
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app(), base_url=BASE, headers=headers) as c:
        r = say(c, "Build a website")
        sid = r["reply"]["session_id"]
        say(c, "my company", sid)
    with TestClient(app(), base_url=BASE, headers=headers) as c:
        r = say(c, "a customer portal", sid)
        answers = {a["slot"]: a["value"] for a in r["session"]["answers"]}
        assert answers == {"purpose": "company", "site_type": "portal"}
        assert r["reply"]["slot"] == "business_name"


@pytest.mark.parametrize(("text", "new"), [
    ("Jack, create a logo for my bakery", True),
    ("Build a professional corporate website", True),
    ("Hey Jack, research the best CRM for small teams", False),  # ambiguous: not confident
    ("It's called Acme Holdings", False),
    ("A contact form and a blog", False),
    ("on my own server", False),
    ("you decide", False),
])
def test_new_command_detection(text: str, new: bool) -> None:
    assert rules.looks_like_new_command(text) is new


def test_voice_answers_go_to_the_waiting_conversation_unless_it_is_a_new_command(
        client: TestClient) -> None:
    eng = client.app.state.svc.discovery  # type: ignore[attr-defined]
    first = eng.message("Build a website", source="voice", continue_active=True)
    answer = eng.message("My company", source="voice", continue_active=True)
    assert answer.session_id == first.session_id
    new = eng.message("Jack, create a logo for my bakery", source="voice", continue_active=True)
    assert new.session_id != first.session_id
    follow = eng.message("Flat and minimal", source="voice", continue_active=True)
    assert follow.session_id == new.session_id  # the newest conversation takes answers


# ------------------------------------------------------------------ voice
def test_voice_answers_follow_up_without_the_wake_word(
        client: TestClient, audio: FakeAudio, asr: FakeRecognizer, tts: FakeTts) -> None:
    engine = client.app.state.svc.voice  # type: ignore[attr-defined]
    engine.followup_wait_s = 3.0
    asr.script["small.en"] = ["Build a professional website.", "My company.", "unused"]
    client.post("/v1/voice/ptt/start", json={})
    audio.speech(0.6)
    time.sleep(0.15)
    client.post("/v1/voice/ptt/stop")
    wait_for(lambda: any("What is the website for?" in t for t in tts.spoken))
    wait_for(lambda: engine.state.value == "listening")  # follow-up: no wake word needed
    assert audio.open
    time.sleep(0.4)  # echo guard
    audio.speech(0.8)
    audio.silence(1.0)
    wait_for(lambda: any(t.startswith("Would you like a corporate website") for t in tts.spoken))
    sessions = client.get("/v1/discovery/sessions").json()
    assert len(sessions) == 1  # the answer went to the same conversation, not a new task
    s = client.get(f"/v1/discovery/sessions/{sessions[0]['id']}").json()
    users = [t for t in s["turns"] if t["role"] == "user"]
    assert [t["source"] for t in users] == ["voice", "voice"]
    assert {a["slot"]: a["value"] for a in s["answers"]}["purpose"] == "company"
    acts = actions(client)
    assert "voice.followup.start" in acts


def test_no_follow_up_listening_in_privacy_mode(
        client: TestClient, audio: FakeAudio, asr: FakeRecognizer, tts: FakeTts) -> None:
    engine = client.app.state.svc.voice  # type: ignore[attr-defined]
    asr.script["small.en"] = ["Build a website."]
    client.post("/v1/voice/ptt/start", json={})
    audio.speech(0.6)
    time.sleep(0.15)
    # Privacy mode switched on while JACK is working on the reply.
    client.post("/v1/voice/ptt/stop")
    client.patch("/v1/voice/settings", json={"privacy_mode": True})
    wait_for(lambda: engine.last_result is not None)
    wait_for(lambda: engine.state.value == "disabled")
    assert not audio.open


# ------------------------------------------------------------------ catalogue integrity
def test_catalogue_covers_the_19_categories_consistently() -> None:
    assert [c.name for c in CATEGORIES] == [
        "Website", "Web application", "Windows application", "Android application",
        "iOS application", "API", "CRM", "ERP", "HRMS", "Trading application", "AI platform",
        "Image generation", "Photo editing", "Video production", "Infrastructure management",
        "Cybersecurity audit", "Research", "Documentation", "Automation"]
    for c in CATEGORIES:
        ids = [s.id for s in c.slots]
        assert len(ids) == len(set(ids)), c.id
        assert any(s.essential for s in c.slots), c.id
        assert sum(s.essential for s in c.slots) <= 7, c.id  # only necessary questions
        for s in c.slots:
            opts = {o.value for o in s.options}
            if s.kind == "choice" and s.default is not None:
                assert s.default in opts, (c.id, s.id)
            if s.kind == "multi":
                assert set(s.default or ()) <= opts, (c.id, s.id)
            for dep, allowed in s.ask_if.items():
                dslot = c.slot(dep)
                assert dslot is not None and set(allowed) <= {o.value for o in dslot.options}
        for k in c.conflicts:
            for slot_id, val in (k.a, k.b):
                sl = c.slot(slot_id)
                assert sl is not None and val in {o.value for o in sl.options}, (c.id, k)
            for slot_id, val in (k.fix_keep_a, k.fix_keep_b):
                sl = c.slot(slot_id)
                assert sl is not None, (c.id, k)
                assert val is None or val in {o.value for o in sl.options}, (c.id, k)


@pytest.mark.parametrize("cat", CATEGORIES, ids=lambda c: c.id)
def test_every_category_is_reachable_by_its_name(cat: Any) -> None:
    assert rules.category_from_answer(cat.name, []) == cat.id


@pytest.mark.parametrize(("text", "expected"), [
    ("Jack, build a professional corporate website.", "website"),
    ("Build a complete e-commerce website", "website"),
    ("Make me an Android app for my gym", "android_app"),
    ("I need an iPhone app for bookings", "ios_app"),
    ("Create a logo for my bakery", "image_generation"),
    ("Remove the background from these product photos", "photo_editing"),
    ("Connect to my Ubuntu server and diagnose the application", "infrastructure"),
    ("Automate my weekly sales report", "automation"),
    ("Build a trading bot for crypto", "trading_app"),
    ("Write a README for my repository", "documentation"),
    ("Set up a CRM for our sales team", "crm"),
    ("We need an HR system with payroll and leave", "hrms"),
    ("Build a REST API for our inventory", "api"),
    ("Make a short promo video for Instagram", "video_production"),
    ("Do a security audit of our web server", "security_audit"),
    ("Build a chatbot that answers from our documents", "ai_platform"),
    ("Build an ERP for our warehouse", "erp"),
    ("Create a Windows desktop app to rename files", "windows_app"),
    ("Build a web app for tracking equipment loans", "web_app"),
])
def test_local_classifier(text: str, expected: str) -> None:
    assert rules.classify(text).category == expected


@pytest.mark.parametrize(("spoken", "name"), [
    ("It's called Green Valley Bakery.", "Green Valley Bakery"),
    ("The business is called Blue Harbor Consulting", "Blue Harbor Consulting"),
    ("Okay, our name is Northwind Traders", "Northwind Traders"),
    ("Contoso", "Contoso"),
])
def test_spoken_names_lose_their_lead_in(spoken: str, name: str) -> None:
    assert rules.strip_fillers(spoken.replace(",", "")) == name


def test_default_phrases_never_select_an_option() -> None:
    for c in CATEGORIES:
        for s in c.slots:
            for p in DEFAULT_PHRASES:
                m = rules.match_slot(s, p)
                assert m.used_default, (c.id, s.id, p)


# ------------------------------------------------------------------ Claude (fake API over HTTP)
@pytest.fixture
def fake() -> Iterator[FakeAnthropic]:
    with FakeAnthropic() as f:
        yield f


@pytest.fixture
def claude(tmp_path: Path, token: str, audio: FakeAudio, asr: FakeRecognizer, tts: FakeTts,
           fake: FakeAnthropic) -> Iterator[TestClient]:
    settings = Settings(session_token=token, port=8765, data_dir=tmp_path / "data",
                        anthropic_base_url=fake.base_url, health_interval_s=0.2)
    creds = MemoryStore()
    app = create_app(settings, audio_backend=audio, recognizer=asr, tts=tts,
                     vad_factory=FakeVad, credentials=creds)
    with TestClient(app, base_url=BASE, headers={"Authorization": f"Bearer {token}"}) as c:
        c.patch("/v1/ai/settings", json={"anthropic": {"max_retries": 0}})
        assert c.put("/v1/ai/anthropic/key", json={"api_key": VALID_KEY}).status_code == 204
        yield c


def _json(obj: Any) -> str:
    return json.dumps(obj)


def test_claude_understands_free_form_answers(claude: TestClient, fake: FakeAnthropic) -> None:
    assert claude.get("/v1/discovery/status").json()["using"] == "claude"
    fake.replies = [
        _json({"category": "website", "confidence": 0.93, "alternatives": ["web_app"]}),
        # Opening request: facts plus an invented slot and an invalid option, both dropped.
        _json({"values": [{"slot": "purpose", "values": ["company"]},
                          {"slot": "budget", "values": ["5000"]},
                          {"slot": "style", "values": ["neon-goth"]}], "conflicts": []}),
        # "We sell handmade furniture; I'd like customers to be able to log in and see orders."
        _json({"values": [{"slot": "site_type", "values": ["portal"]},
                          {"slot": "features", "values": ["accounts", "contact_form"]}],
               "conflicts": []}),
    ]
    r = say(claude, "Jack, I need a website for my business")
    sid, tid = r["reply"]["session_id"], r["reply"]["task_id"]
    assert r["session"]["category"] == "website"
    assert r["session"]["category_source"] == "claude"
    answers = {a["slot"]: a["value"] for a in r["session"]["answers"]}
    assert answers == {"purpose": "company"}
    assert r["reply"]["slot"] == "site_type"
    r = say(claude, "We sell handmade furniture; I'd like customers to be able to log in and "
                    "see their orders.", sid)
    answers = {a["slot"]: a for a in r["session"]["answers"]}
    assert answers["site_type"]["value"] == "portal" and answers["site_type"]["source"] == "user"
    assert answers["features"]["value"] == ["accounts", "contact_form"]
    assert answers["features"]["source"] == "inferred"
    assert r["reply"]["slot"] == "business_name"  # features not asked: already known

    bodies = [q["body"] for q in fake.requests]
    assert len(bodies) == 3
    for b in bodies:
        fmt = b["output_config"]["format"]
        assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
        assert b["output_config"]["effort"] == "low" and b["max_tokens"] == 1024
        assert "JACK" in b["system"]
    assert "website: Website" in bodies[0]["messages"][0]["content"]
    assert "JACK just asked: \"Would you like a corporate website" in \
        bodies[2]["messages"][0]["content"]
    usage = claude.get("/v1/ai/usage/records").json()["items"]
    assert {u["purpose"] for u in usage} == {"discovery.classify", "discovery.extract"}
    assert all(u["task_id"] == tid and u["succeeded"] for u in usage)


def test_claude_conflicts_are_asked_once(claude: TestClient, fake: FakeAnthropic) -> None:
    fake.replies = [
        _json({"category": "research", "confidence": 0.9, "alternatives": []}),
        _json({"values": [{"slot": "question", "values": ["Cheapest flights to Lisbon"]}],
               "conflicts": []}),
        _json({"values": [{"slot": "depth", "values": ["quick"]}],
               "conflicts": ["You asked for a quick answer but also a full comparison of every "
                             "airline."]}),
    ]
    r = say(claude, "Research cheap flights to Lisbon")
    sid = r["reply"]["session_id"]
    assert r["reply"]["slot"] == "depth"
    r = say(claude, "quick, but compare every airline in detail", sid)
    assert r["session"]["status"] == "resolving_conflict"
    assert r["reply"]["text"].startswith("You asked for a quick answer")
    r = say(claude, "Just the three cheapest", sid)
    assert r["session"]["status"] == "ready"
    notes = r["session"]["spec"]["notes"]
    assert any("Just the three cheapest" in n for n in notes)


def test_claude_failure_falls_back_to_local_rules(claude: TestClient,
                                                  fake: FakeAnthropic) -> None:
    fake.mode = "server_error"
    r = say(claude, "Jack, build a professional corporate website")
    assert r["session"]["category"] == "website"
    assert r["session"]["category_source"] == "local"
    assert r["reply"]["slot"] == "business_name"
    assert any("local rules were used" in n for n in r["session"]["notes"])
    usage = claude.get("/v1/ai/usage/records").json()["items"]
    assert usage and not any(u["succeeded"] for u in usage)  # failures recorded, not hidden


def test_invalid_claude_json_falls_back(claude: TestClient, fake: FakeAnthropic) -> None:
    fake.replies = ["this is not json", "{\"values\": 5}"]
    r = say(claude, "Make me an Android app")
    assert r["session"]["category"] == "android_app"
    assert r["session"]["category_source"] == "local"


def test_local_mode_never_calls_claude(claude: TestClient, fake: FakeAnthropic) -> None:
    claude.patch("/v1/discovery/settings", json={"engine": "local"})
    assert claude.get("/v1/discovery/status").json()["using"] == "local"
    say(claude, "Build a website")
    assert fake.requests == []


def test_budget_limit_stops_claude_but_not_discovery(claude: TestClient,
                                                     fake: FakeAnthropic) -> None:
    claude.patch("/v1/ai/settings", json={"limits": {"monthly_usd": "0"}})
    r = say(claude, "Build a website")
    assert r["session"]["category"] == "website"
    assert any("(budget)" in n for n in r["session"]["notes"])
    assert fake.requests == []
