"""Milestone 6: durable task orchestration on a real Temporal server.

Uses the Temporal CLI built by scripts/build_temporal.py (JACK_TEMPORAL_BIN) and the local fake
Anthropic API. Skipped when the Temporal binary isn't available.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fake_anthropic import VALID_KEY, FakeAnthropic
from fastapi.testclient import TestClient

from conftest import BASE, FakeAudio, FakeRecognizer, FakeTts, FakeVad
from jack_api import app as app_module
from jack_api.ai.credentials import MemoryStore
from jack_api.app import create_app
from jack_api.config import Settings
from jack_api.orchestrator import activities as acts_module
from jack_api.orchestrator.executors import StepContext, StepResult, default_registry
from jack_api.orchestrator.plans import DELIVER, StepDef

TEMPORAL = os.environ.get("JACK_TEMPORAL_BIN") or "/home/user/tools/temporal/temporal"
pytestmark = pytest.mark.skipif(not Path(TEMPORAL).is_file(),
                                reason="Temporal binary not built (scripts/build_temporal.py)")


@pytest.fixture
def fake() -> Iterator[FakeAnthropic]:
    with FakeAnthropic() as f:
        f.reply = "# Answer\n\nObsidian suits a team of five on Windows.\n"
        yield f


@pytest.fixture(autouse=True)
def _temporal_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JACK_TEMPORAL", "on")
    monkeypatch.setenv("JACK_TEMPORAL_BIN", TEMPORAL)


class Jack:
    """One running JACK service (Temporal on, SQLite) that can be restarted on the same data."""

    def __init__(self, tmp_path: Path, token: str, fake: FakeAnthropic, audio: FakeAudio,
                 asr: FakeRecognizer, tts: FakeTts, *, key: bool = True) -> None:
        self.settings = Settings(session_token=token, port=8765, data_dir=tmp_path / "data",
                                 anthropic_base_url=fake.base_url, health_interval_s=0.2)
        self.creds = MemoryStore()
        self.args = (token, audio, asr, tts)
        self.key = key
        self.c: TestClient | None = None

    def __enter__(self) -> TestClient:
        token, audio, asr, tts = self.args
        app = create_app(self.settings, audio_backend=audio, recognizer=asr, tts=tts,
                         vad_factory=FakeVad, credentials=self.creds)
        self.c = TestClient(app, base_url=BASE, headers={"Authorization": f"Bearer {token}"})
        self.c.__enter__()
        self.c.patch("/v1/ai/settings", json={"anthropic": {"max_retries": 0}})
        # Requirement discovery is tested in M5; here only task steps call (the fake) Claude.
        self.c.patch("/v1/discovery/settings", json={"engine": "local"})
        if self.key:
            assert self.c.put("/v1/ai/anthropic/key", json={"api_key": VALID_KEY}).status_code \
                == 204
        return self.c

    def __exit__(self, *exc: object) -> None:
        assert self.c is not None
        self.c.__exit__(None, None, None)


@pytest.fixture
def jack(tmp_path: Path, token: str, fake: FakeAnthropic, audio: FakeAudio,
         asr: FakeRecognizer, tts: FakeTts) -> Jack:
    return Jack(tmp_path, token, fake, audio, asr, tts)


def wait(cond: Callable[[], Any], timeout: float = 60, every: float = 0.25) -> Any:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = cond()
        if last:
            return last
        time.sleep(every)
    raise AssertionError(f"condition not met in {timeout}s (last: {last!r})")


def status(c: TestClient, tid: str) -> str:
    return c.get(f"/v1/tasks/{tid}").json()["status"]  # type: ignore[no-any-return]


def execution(c: TestClient, tid: str) -> dict[str, Any]:
    return c.get(f"/v1/tasks/{tid}/execution").json()  # type: ignore[no-any-return]


def steps(c: TestClient, tid: str) -> dict[str, dict[str, Any]]:
    return {s["key"]: s for s in execution(c, tid)["steps"]}


def research(c: TestClient) -> tuple[str, dict[str, Any]]:
    r = c.post("/v1/discovery/messages",
               json={"text": "Research the best note-taking apps for a small team"}).json()
    sid = r["reply"]["session_id"]
    c.post("/v1/discovery/messages", json={"text": "Which suits five people on Windows",
                                           "session_id": sid})
    r = c.post("/v1/discovery/messages", json={"text": "A quick answer", "session_id": sid})
    return r.json()["reply"]["task_id"], r.json()


# ------------------------------------------------------------------ happy path
def test_research_task_runs_to_completion_with_real_artifacts(jack: Jack,
                                                              fake: FakeAnthropic) -> None:
    with jack as c:
        assert c.get("/v1/orchestrator/status").json()["status"] == "healthy"
        tid, r = research(c)
        assert "I've started on it" in r["reply"]["text"]
        wait(lambda: status(c, tid) == "COMPLETED")
        ex = execution(c, tid)
        assert [s["key"] for s in ex["steps"]] == ["research", "deliver"]
        assert all(s["status"] == "done" and s["attempts"] == 1 for s in ex["steps"])
        assert ex["steps"][0]["agent_role"] == "Research Agent"
        names = {a["name"]: a for a in ex["artifacts"]}
        assert set(names) == {"answer.md", "summary.md"}
        text = c.get(f"/v1/tasks/{tid}/artifacts/{names['answer.md']['id']}").text
        assert "Obsidian suits a team of five" in text
        assert Path(names["answer.md"]["path"]).is_relative_to(jack.settings.data_dir /
                                                               "workspaces" / tid)
        assert ex["summary"] == "Delivered 1 document: answer.md"
        assert ex["runs"][0]["status"] == "completed"
        timeline = [e["to_status"] for e in c.get(f"/v1/tasks/{tid}").json()["events"]]
        assert timeline[-3:] == ["PLANNING", "EXECUTION", "COMPLETED"]
        # The step prompt carried the approved specification.
        step_req = fake.requests[-1]["body"]
        assert "Which suits five people on Windows" in step_req["messages"][0]["content"]
        usage = c.get("/v1/ai/usage/records").json()["items"]
        assert any(u["purpose"] == "task.step" and u["task_id"] == tid for u in usage)
        acts = [a["action"] for a in c.get("/v1/audit", params={"limit": 200}).json()["items"]]
        for a in ("task.workflow.start", "task.plan", "task.step.start", "task.step.done"):
            assert a in acts


def test_software_task_stops_honestly_where_capabilities_are_missing(jack: Jack) -> None:
    with jack as c:
        eng = c.app.state.svc.discovery  # type: ignore[attr-defined]
        r = eng.message("Build a professional corporate website", source="typed")
        sid = r.session_id
        for answer in ("Acme Holdings", "a contact form", "design them for me",
                       "on my own server"):
            r = eng.message(answer, source="typed", session_id=sid)
        assert r.status == "awaiting_approval"
        pending = c.get("/v1/approvals").json()
        assert [a["action"] for a in pending] == ["task.execute"]
        assert pending[0]["target"] == f"task:{r.task_id}" and pending[0]["nonce"]
        r = eng.message("Yes, go ahead", source="voice", session_id=sid)
        assert "I've started on it" in r.text
        assert c.get("/v1/approvals").json() == []  # decided, by voice
        tid = r.task_id
        wait(lambda: steps(c, tid).get("structure", {}).get("status") == "blocked")
        st = steps(c, tid)
        assert st["architecture"]["status"] == "done"
        assert "Milestone 11" in st["structure"]["blocked_reason"]
        assert list(st) == ["architecture", "structure", "backend", "frontend", "integrations",
                            "testing", "security", "release", "deploy", "deliver"]
        assert st["deploy"]["needs_approval"] and not st["deploy"]["idempotent"]
        task = c.get(f"/v1/tasks/{tid}").json()
        assert task["status"] == "PAUSED" and "Milestone 11" in task["status_reason"]
        # Resuming re-checks honestly and pauses again: nothing pretends to build.
        c.post(f"/v1/tasks/{tid}/resume", json={})
        time.sleep(2)
        assert status(c, tid) == "PAUSED"
        assert steps(c, tid)["structure"]["attempts"] == 0
        approved = c.get("/v1/approvals", params={"status": "approved"}).json()
        assert approved[0]["decided_via"] == "voice"


def test_reasoning_waits_for_claude_then_continues(tmp_path: Path, token: str,
                                                  fake: FakeAnthropic, audio: FakeAudio,
                                                  asr: FakeRecognizer, tts: FakeTts) -> None:
    j = Jack(tmp_path, token, fake, audio, asr, tts, key=False)
    with j as c:
        tid, r = research(c)
        wait(lambda: status(c, tid) == "PAUSED")
        assert "Needs Claude" in c.get(f"/v1/tasks/{tid}").json()["status_reason"]
        assert c.put("/v1/ai/anthropic/key", json={"api_key": VALID_KEY}).status_code == 204
        wait(lambda: status(c, tid) == "COMPLETED")  # the key unblocked it, no restart needed


def test_rejected_key_pauses_the_task_instead_of_failing_it(jack: Jack,
                                                           fake: FakeAnthropic) -> None:
    with jack as c:
        wrong = "sk-ant-api03-" + "W" * 40  # well-formed, but the API rejects it
        assert c.put("/v1/ai/anthropic/key", json={"api_key": wrong}).status_code == 204
        tid, _ = research(c)
        wait(lambda: status(c, tid) == "PAUSED")
        reason = c.get(f"/v1/tasks/{tid}").json()["status_reason"]
        assert "rejected the API key" in reason
        assert steps(c, tid)["research"]["status"] == "blocked"
        time.sleep(2)
        assert status(c, tid) == "PAUSED"  # waits; doesn't spin or burn retries
        assert c.put("/v1/ai/anthropic/key", json={"api_key": VALID_KEY}).status_code == 204
        wait(lambda: status(c, tid) == "COMPLETED")


# ------------------------------------------------------------------ controls
def test_pause_finishes_the_step_then_waits_and_resume_continues(jack: Jack,
                                                                 fake: FakeAnthropic) -> None:
    fake.delay = 3
    with jack as c:
        tid, _ = research(c)
        wait(lambda: steps(c, tid).get("research", {}).get("status") == "running")
        c.post(f"/v1/tasks/{tid}/pause", json={})
        wait(lambda: status(c, tid) == "PAUSED")
        st = steps(c, tid)
        assert st["research"]["status"] == "done" and st["deliver"]["status"] == "pending"
        fake.delay = 0
        c.post(f"/v1/tasks/{tid}/resume", json={})
        wait(lambda: status(c, tid) == "COMPLETED")


def test_cancel_stops_a_running_step(jack: Jack, fake: FakeAnthropic) -> None:
    fake.delay = 30
    with jack as c:
        tid, _ = research(c)
        wait(lambda: steps(c, tid).get("research", {}).get("status") == "running")
        c.post(f"/v1/tasks/{tid}/cancel", json={"reason": "Changed my mind"})
        wait(lambda: status(c, tid) == "CANCELLED", timeout=30)
        assert c.get(f"/v1/tasks/{tid}").json()["status_reason"] == "Changed my mind"
        assert execution(c, tid)["runs"][0]["status"] == "cancelled"


def test_failed_task_can_be_retried_from_where_it_stopped(jack: Jack,
                                                          fake: FakeAnthropic) -> None:
    with jack as c:
        eng = c.app.state.svc.discovery  # type: ignore[attr-defined]
        r = eng.message("Write a README for my project", source="typed")
        eng.message("How to install and run it", source="typed", session_id=r.session_id)
        fake.ok_budget = 1  # the outline succeeds, every attempt at the next step fails
        r = eng.message("Developers", source="typed", session_id=r.session_id)
        tid = r.task_id
        wait(lambda: status(c, tid) == "FAILED", timeout=60)
        st = steps(c, tid)
        assert st["write"]["status"] == "failed" and st["write"]["attempts"] == 3
        fake.ok_budget = None
        assert c.post(f"/v1/tasks/{tid}/retry").status_code == 200
        wait(lambda: status(c, tid) == "COMPLETED")
        st = steps(c, tid)
        assert st["outline"]["attempts"] == 1  # finished steps are never redone
        assert c.post(f"/v1/tasks/{tid}/retry").status_code == 409


# ------------------------------------------------------------------ approvals inside a workflow
@pytest.fixture
def risky_plan(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    ran: list[str] = []

    def risky(ctx: StepContext) -> StepResult:
        ran.append(ctx.step["key"])
        time.sleep(float(os.environ.get("RISKY_SLEEP", "0")))
        return StepResult(output={"done": True})

    reg = default_registry()
    reg["test.risky"] = risky
    monkeypatch.setattr(app_module, "default_registry", lambda: reg)
    monkeypatch.setattr(acts_module, "build_plan", lambda spec: [
        StepDef("risky", "Change something important", "test.risky", "DevOps Engineer",
                idempotent=False, needs_approval=True), DELIVER])
    return ran


def _plain_task(c: TestClient) -> str:
    """A task that goes straight to planning (no discovery session)."""
    tid: str = c.post("/v1/tasks", json={"command_text": "risky job",
                                         "source": "text"}).json()["id"]
    c.app.state.svc.orchestrator.start_task(tid)  # type: ignore[attr-defined]
    return tid


def test_step_approval_is_bound_verified_and_single_use(jack: Jack,
                                                        risky_plan: list[str]) -> None:
    with jack as c:
        tid = _plain_task(c)
        wait(lambda: status(c, tid) == "WAITING_FOR_APPROVAL")
        a = c.get("/v1/approvals").json()[0]
        assert a["action"] == "step.risky" and a["target"] == f"task:{tid}/step:risky"
        assert a["risk"] == "high" and a["scope"]["step"] == "risky"
        # A forged signal straight to Temporal's (unauthenticated) port approves nothing.
        c.app.state.svc.orchestrator.signal(tid, "approval_decided", a["id"])  # type: ignore[attr-defined]
        time.sleep(2)
        assert status(c, tid) == "WAITING_FOR_APPROVAL" and risky_plan == []
        # A decision must echo the request's nonce.
        bad = c.post(f"/v1/approvals/{a['id']}/decide",
                     json={"decision": "approve", "nonce": "x" * 20})
        assert bad.status_code == 409 and bad.json()["error"]["code"] == "approval_stale"
        ok = c.post(f"/v1/approvals/{a['id']}/decide",
                    json={"decision": "approve", "nonce": a["nonce"]})
        assert ok.status_code == 200 and ok.json()["status"] == "approved"
        again = c.post(f"/v1/approvals/{a['id']}/decide",
                       json={"decision": "approve", "nonce": a["nonce"]})
        assert again.status_code == 409  # single use
        wait(lambda: status(c, tid) == "COMPLETED")
        assert risky_plan == ["risky"]
        audit = c.get("/v1/audit", params={"limit": 200}).json()["items"]
        denied = [x for x in audit if x["action"] == "approval.decide"
                  and x["outcome"] == "denied"]
        assert {d["details"]["reason"] for d in denied} == {"nonce", "approved"}


def test_denied_approval_cancels_the_task(jack: Jack, risky_plan: list[str]) -> None:
    with jack as c:
        tid = _plain_task(c)
        wait(lambda: c.get("/v1/approvals").json())
        a = c.get("/v1/approvals").json()[0]
        c.post(f"/v1/approvals/{a['id']}/decide", json={"decision": "deny",
                                                         "nonce": a["nonce"]})
        wait(lambda: status(c, tid) == "CANCELLED")
        assert risky_plan == []


def test_expired_approval_pauses_and_resume_asks_again(jack: Jack, risky_plan: list[str],
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import timedelta

    monkeypatch.setattr(acts_module, "STEP_APPROVAL_TTL", timedelta(seconds=2))
    with jack as c:
        tid = _plain_task(c)
        wait(lambda: c.get("/v1/approvals").json())
        first = c.get("/v1/approvals").json()[0]["id"]
        wait(lambda: status(c, tid) == "PAUSED", timeout=30)
        assert "expired" in c.get(f"/v1/tasks/{tid}").json()["status_reason"]
        c.post(f"/v1/tasks/{tid}/resume", json={})
        wait(lambda: [a for a in c.get("/v1/approvals").json() if a["id"] != first])
        assert risky_plan == []


# ------------------------------------------------------------------ restarts
def test_running_step_survives_a_restart(jack: Jack, fake: FakeAnthropic) -> None:
    fake.delay = 4
    with jack as c:
        tid, _ = research(c)
        wait(lambda: steps(c, tid).get("research", {}).get("status") == "running")
    # Service stopped mid-step (the worker and the Temporal server with it); start again.
    fake.delay = 0
    with jack as c:
        rec = c.get("/v1/orchestrator/status").json()["recovered"]
        assert rec["resumed"] == 1
        wait(lambda: status(c, tid) == "COMPLETED", timeout=90)
        st = steps(c, tid)
        assert st["research"]["attempts"] >= 2  # repeated: it is safe to repeat
        notes = c.get("/v1/notifications").json()["items"]
        assert any(n["kind"] == "task.recovered" for n in notes)


def test_unsafe_step_interrupted_by_a_restart_needs_review(
        jack: Jack, risky_plan: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RISKY_SLEEP", "8")
    with jack as c:
        tid = _plain_task(c)
        wait(lambda: c.get("/v1/approvals").json())
        a = c.get("/v1/approvals").json()[0]
        c.post(f"/v1/approvals/{a['id']}/decide", json={"decision": "approve",
                                                         "nonce": a["nonce"]})
        wait(lambda: steps(c, tid)["risky"]["status"] == "running")
    monkeypatch.setenv("RISKY_SLEEP", "0")
    with jack as c:
        wait(lambda: status(c, tid) == "WAITING_FOR_INFORMATION", timeout=90)
        assert steps(c, tid)["risky"]["status"] == "needs_review"
        assert "not safe to repeat" in c.get(f"/v1/tasks/{tid}").json()["status_reason"]
        c.post(f"/v1/tasks/{tid}/resume", json={})  # the user reviewed it: run it again
        wait(lambda: status(c, tid) == "COMPLETED", timeout=60)


def test_tasks_waiting_in_planning_start_when_orchestration_comes_back(
        tmp_path: Path, token: str, fake: FakeAnthropic, audio: FakeAudio,
        asr: FakeRecognizer, tts: FakeTts) -> None:
    j = Jack(tmp_path, token, fake, audio, asr, tts)
    j.settings = Settings(**{**j.settings.model_dump(), "temporal": "off"})
    with j as c:
        tid, r = research(c)
        assert "waits in planning" in r["reply"]["text"]
        assert status(c, tid) == "PLANNING"
    j.settings = Settings(**{**j.settings.model_dump(), "temporal": "on"})
    with j as c:
        assert c.get("/v1/orchestrator/status").json()["recovered"]["started"] == 1
        wait(lambda: status(c, tid) == "COMPLETED")


def test_lost_workflow_history_is_flagged_not_guessed(jack: Jack, fake: FakeAnthropic) -> None:
    fake.delay = 30
    with jack as c:
        tid, _ = research(c)
        wait(lambda: steps(c, tid).get("research", {}).get("status") == "running")
    (jack.settings.data_dir / "temporal" / "temporal.db").unlink()
    fake.delay = 0
    with jack as c:
        assert c.get("/v1/orchestrator/status").json()["recovered"]["needs_review"] == 1
        task = c.get(f"/v1/tasks/{tid}").json()
        assert task["status"] == "WAITING_FOR_INFORMATION"
        assert "couldn't find this task's progress" in task["status_reason"]

