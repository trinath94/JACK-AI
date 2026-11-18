"""Temporal activities: every side effect of a task's workflow happens here.

They read and write the authoritative state in JACK's database (tasks, steps, approvals,
artifacts, audit) so that a workflow replay never repeats or loses a recorded effect.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from temporalio import activity
from temporalio.exceptions import ApplicationError

from jack_api.audit import AuditLog
from jack_api.db import (
    Database,
    RequirementSession,
    Task,
    TaskArtifact,
    TaskStep,
    WorkflowRun,
    utcnow,
)
from jack_api.notifications import NotificationCentre
from jack_api.orchestrator.approvals import ApprovalService, aware, scope_hash
from jack_api.orchestrator.executors import (
    Blocked,
    Executor,
    StepContext,
    availability,
    sha256_file,
)
from jack_api.orchestrator.plans import build_plan
from jack_api.tasks import TaskStatus, TaskStore, move_to

log = logging.getLogger(__name__)
S = TaskStatus
ACTOR = "jack"
STEP_APPROVAL_TTL = timedelta(hours=24)
HEARTBEAT_S = 5.0


class Deps:
    """What activities need from the service. Set once at worker start."""

    def __init__(self, *, db: Database, tasks: TaskStore, audit: AuditLog,
                 approvals: ApprovalService, notifications: NotificationCentre,
                 publish: Callable[[str, dict[str, Any]], None],
                 publish_task: Callable[[str, Task], None], workspaces: Path,
                 executors: dict[str, Executor],
                 complete: Callable[..., dict[str, Any]] | None,
                 reasoning_ready: Callable[[], bool]) -> None:
        self.db = db
        self.tasks = tasks
        self.audit = audit
        self.approvals = approvals
        self.notes = notifications
        self.publish = publish
        self.publish_task = publish_task
        self.workspaces = workspaces
        self.executors = executors
        self.complete = complete
        self.reasoning_ready = reasoning_ready


class Activities:
    def __init__(self, deps: Deps) -> None:
        self.d = deps

    # ------------------------------------------------------------------ helpers
    def _move(self, task_id: str, target: TaskStatus, reason: str) -> None:
        move_to(self.d.tasks, task_id, target, reason, ACTOR, self.d.publish_task)

    def _step(self, step_id: str) -> TaskStep:
        with self.d.db.session() as s:
            st = s.get(TaskStep, step_id)
            if st is None:
                raise ApplicationError(f"step {step_id} not found", non_retryable=True)
            return st

    def _update_step(self, step_id: str, **fields: Any) -> TaskStep:
        with self.d.db.session() as s:
            st = s.get(TaskStep, step_id)
            assert st is not None
            for k, v in fields.items():
                setattr(st, k, v)
            st.updated_at = utcnow()
        self.d.publish("task.step", {"task_id": st.task_id, "step_id": st.id, "key": st.key,
                                     "status": st.status})
        return st

    def _spec(self, task_id: str) -> dict[str, Any]:
        with self.d.db.session() as s:
            row = s.scalar(select(RequirementSession).where(RequirementSession.task_id == task_id))
            task = s.get(Task, task_id)
        if row is not None and row.spec:
            return dict(row.spec)
        return {"title": task.title if task else "Task", "category": "", "category_name": "",
                "summary": task.command_text if task else "", "requirements": [],
                "assumptions": []}

    # ------------------------------------------------------------------ activities
    @activity.defn(name="plan_task")
    def plan_task(self, task_id: str) -> list[str]:
        """Create the steps once (idempotent) and return their ids in order."""
        with self.d.db.session() as s:
            existing = list(s.scalars(select(TaskStep).where(TaskStep.task_id == task_id)
                                      .order_by(TaskStep.seq)))
        if not existing:
            spec = self._spec(task_id)
            plan = build_plan(spec)
            with self.d.db.session() as s:
                for i, sd in enumerate(plan, 1):
                    s.add(TaskStep(task_id=task_id, seq=i, key=sd.key, title=sd.title,
                                   kind=sd.kind, agent_role=sd.role, idempotent=sd.idempotent,
                                   needs_approval=sd.needs_approval,
                                   instructions=sd.instructions, status="pending", attempts=0,
                                   updated_at=utcnow()))
            self.d.audit.record("task.plan", outcome="allowed", actor_type="system",
                                target=f"task:{task_id}",
                                details={"steps": [p.key for p in plan], "source": "template"})
            with self.d.db.session() as s:
                existing = list(s.scalars(select(TaskStep).where(TaskStep.task_id == task_id)
                                          .order_by(TaskStep.seq)))
            self.d.publish("task.step", {"task_id": task_id, "planned": len(existing)})
        task, _ = self.d.tasks.get(task_id)
        if task.status == S.RECEIVED:  # a task that didn't go through discovery
            self._move(task_id, S.UNDERSTANDING, "No requirements conversation for this task")
            task, _ = self.d.tasks.get(task_id)
        if task.status in (S.UNDERSTANDING, S.REQUIREMENTS):
            self._move(task_id, S.PLANNING, "Planning")
        return [st.id for st in existing]

    @activity.defn(name="prepare_step")
    def prepare_step(self, task_id: str, step_id: str) -> dict[str, Any]:
        st = self._step(step_id)
        if st.status in ("done", "skipped"):
            return {"status": "done"}
        if st.status == "needs_review":
            self._move(task_id, S.WAITING_FOR_INFORMATION,
                       f"“{st.title}” was interrupted and is not safe to repeat automatically. "
                       "Check it, then resume to run it again or cancel the task.")
            return {"status": "needs_review"}
        if st.status == "blocked" and st.blocked_reason:
            # Blocked while running (e.g. the key was rejected): stay put until the user
            # resumes or the setup changes, which re-opens the step (set_resumed).
            self._move(task_id, S.EXECUTION, f"Working on “{st.title}”")
            self._move(task_id, S.PAUSED, f"Waiting at “{st.title}”: {st.blocked_reason}")
            return {"status": "blocked", "reason": st.blocked_reason}
        ok, why = availability(st.kind, reasoning_ready=self.d.reasoning_ready(),
                               registry=self.d.executors)
        if not ok:
            if st.status != "blocked" or st.blocked_reason != why:
                self._update_step(step_id, status="blocked", blocked_reason=why)
                self.d.audit.record("task.step.blocked", outcome="info", actor_type="system",
                                    target=f"task:{task_id}",
                                    details={"step": st.key, "reason": why})
            self._move(task_id, S.EXECUTION, f"Working on “{st.title}”")
            self._move(task_id, S.PAUSED, f"Waiting at “{st.title}”: {why}")
            return {"status": "blocked", "reason": why}
        if st.needs_approval:
            spec_hash = scope_hash(self._spec(task_id))
            approved = st.approval_id and self.d.approvals.get(st.approval_id).status == \
                "approved"
            if not approved:
                a = self.d.approvals.request(
                    task_id=task_id, step_id=step_id, action=f"step.{st.key}",
                    target=f"task:{task_id}/step:{st.key}",
                    scope={"step": st.key, "spec_sha256": spec_hash},
                    summary=f"Allow JACK to “{st.title}” for this task",
                    expires_in=STEP_APPROVAL_TTL, risk="high" if not st.idempotent else "medium")
                self._update_step(step_id, status="waiting_approval", approval_id=a.id,
                                  blocked_reason=None)
                self._move(task_id, S.EXECUTION, f"Working on “{st.title}”")
                self._move(task_id, S.WAITING_FOR_APPROVAL, f"Approval needed: {st.title}")
                remaining = max(1, int((aware(a.expires_at) - utcnow()).total_seconds()))
                return {"status": "needs_approval", "approval_id": a.id,
                        "expires_in_s": remaining}
        self._update_step(step_id, status="pending", blocked_reason=None)
        self._move(task_id, S.EXECUTION, f"Working on “{st.title}”")
        return {"status": "ready", "idempotent": st.idempotent}

    @activity.defn(name="run_step")
    def run_step(self, task_id: str, step_id: str) -> dict[str, Any]:
        st = self._step(step_id)
        if st.status == "done":
            return {"status": "done"}  # finished by an earlier attempt that then lost contact
        info = activity.info()
        self._update_step(step_id, status="running", attempts=st.attempts + 1,
                          started_at=utcnow(), error=None)
        self.d.audit.record("task.step.start", outcome="info", actor_type="system",
                            target=f"task:{task_id}",
                            details={"step": st.key, "attempt": info.attempt})
        task, _ = self.d.tasks.get(task_id)
        with self.d.db.session() as s:
            prev = [{"key": p.key, "title": p.title, "output": p.output} for p in s.scalars(
                select(TaskStep).where(TaskStep.task_id == task_id, TaskStep.status == "done")
                .order_by(TaskStep.seq))]
        ctx = StepContext(task_id=task_id, title=task.title, spec=self._spec(task_id),
                          step={"key": st.key, "title": st.title,
                                "instructions": st.instructions},
                          previous=prev, workspace=self.d.workspaces / task_id,
                          complete=self.d.complete, cancelled=activity.is_cancelled)
        executor = self.d.executors[st.kind]
        result_box: dict[str, Any] = {}

        def work() -> None:
            try:
                result_box["ok"] = executor(ctx)
            except BaseException as exc:  # noqa: BLE001 - re-raised on the activity thread
                result_box["err"] = exc

        t = threading.Thread(target=work, name=f"step-{st.key}", daemon=True)
        t.start()
        while t.is_alive():
            activity.heartbeat({"step": st.key})
            if activity.is_cancelled():
                if st.idempotent:
                    self._update_step(step_id, status="pending", error="Stopped while running")
                    raise ApplicationError("cancelled", type="Cancelled", non_retryable=True)
                # Stopped part-way and not safe to repeat: the user decides.
                self._update_step(step_id, status="needs_review",
                                  error="Stopped while running; not repeated automatically")
                raise ApplicationError("interrupted", type="Interrupted", non_retryable=True)
            t.join(HEARTBEAT_S)
        if "err" in result_box:
            exc = result_box["err"]
            if isinstance(exc, Blocked):
                self._update_step(step_id, status="blocked", blocked_reason=str(exc))
                raise ApplicationError(str(exc), type="Blocked", non_retryable=True)
            msg = f"{type(exc).__name__}: {exc}"[:1000]
            self._update_step(step_id, status="failed", error=msg)
            self.d.audit.record("task.step.error", outcome="error", actor_type="system",
                                target=f"task:{task_id}", details={"step": st.key,
                                                                   "error": msg[:300]})
            raise ApplicationError(msg, type="StepFailed")
        res = result_box["ok"]
        with self.d.db.session() as s:
            for a in res.artifacts:
                p = Path(a["path"])
                old = s.scalar(select(TaskArtifact).where(TaskArtifact.task_id == task_id,
                                                          TaskArtifact.name == a["name"]))
                if old is not None:
                    s.delete(old)
                s.add(TaskArtifact(task_id=task_id, step_id=step_id, name=a["name"],
                                   path=str(p), kind=a["kind"], size_bytes=p.stat().st_size,
                                   sha256=sha256_file(p), created_at=utcnow()))
        self._update_step(step_id, status="done", output=res.output, finished_at=utcnow(),
                          blocked_reason=None)
        self.d.audit.record("task.step.done", outcome="allowed", actor_type="system",
                            target=f"task:{task_id}", details={"step": st.key})
        return {"status": "done"}

    @activity.defn(name="mark_needs_review")
    def mark_needs_review(self, task_id: str, step_id: str, why: str) -> None:
        st = self._update_step(step_id, status="needs_review", error=why[:1000])
        self.d.audit.record("task.step.needs_review", outcome="info", actor_type="system",
                            target=f"task:{task_id}", details={"step": st.key,
                                                               "reason": why[:300]})
        self.d.notes.create("task.needs_review", "A task needs your review",
                            f"“{st.title}” was interrupted and isn't safe to repeat "
                            "automatically. Open the task to resume or cancel it.",
                            level="warning", task_id=task_id)

    @activity.defn(name="check_approval")
    def check_approval(self, task_id: str, step_id: str, approval_id: str) -> str:
        """The authoritative answer comes from the database, never from the signal."""
        a = self.d.approvals.get(approval_id)
        if a.status == "approved":
            return "approved"
        if a.status in ("expired", "withdrawn"):
            st = self._update_step(step_id, status="pending", approval_id=None)
            self._move(task_id, S.PAUSED, f"The approval for “{st.title}” expired. Resume to "
                       "ask again.")
            return "expired"
        if a.status == "denied":
            self._update_step(step_id, status="skipped", blocked_reason="You declined")
            return "denied"
        return "pending"

    @activity.defn(name="set_paused")
    def set_paused(self, task_id: str, reason: str) -> None:
        task, _ = self.d.tasks.get(task_id)
        if task.status not in (S.PAUSED, S.COMPLETED, S.CANCELLED, S.FAILED):
            self._move(task_id, S.PAUSED, reason)

    @activity.defn(name="set_resumed")
    def set_resumed(self, task_id: str, by_user: bool = True) -> None:
        """Blocked steps are checked afresh. Interrupted steps that aren't safe to repeat run
        again only when the *user* resumed (that is their review), never on a setup change."""
        reopen = ("needs_review", "blocked") if by_user else ("blocked",)
        with self.d.db.session() as s:
            for st in s.scalars(select(TaskStep).where(
                    TaskStep.task_id == task_id, TaskStep.status.in_(reopen))):
                st.status = "pending"
                st.blocked_reason = None
                st.updated_at = utcnow()
        task, _ = self.d.tasks.get(task_id)
        if task.status in (S.PAUSED, S.WAITING_FOR_INFORMATION, S.WAITING_FOR_APPROVAL):
            self._move(task_id, TaskStatus(task.resume_status or S.EXECUTION), "Resumed")

    @activity.defn(name="finish_task")
    def finish_task(self, task_id: str, outcome: str, reason: str) -> None:
        run_status = {"completed": "completed", "cancelled": "cancelled"}.get(outcome, "failed")
        with self.d.db.session() as s:
            for r in s.scalars(select(WorkflowRun).where(WorkflowRun.task_id == task_id,
                                                         WorkflowRun.status == "running")):
                r.status = run_status
                r.ended_at = utcnow()
            steps = list(s.scalars(select(TaskStep).where(TaskStep.task_id == task_id)))
        self.d.approvals.withdraw_for_task(task_id)
        if outcome == "completed":
            deliver = next((x for x in steps if x.key == "deliver" and x.output), None)
            summary = (deliver.output or {}).get("summary") if deliver else "Completed."
            with self.d.db.session() as s:
                t = s.get(Task, task_id)
                assert t is not None
                t.summary = summary
            self._move(task_id, S.COMPLETED, summary or "Completed")
        elif outcome == "cancelled":
            self._move(task_id, S.CANCELLED, reason or "Cancelled")
        else:
            self._move(task_id, S.FAILED, reason[:500] or "Failed")

    def all(self) -> list[Callable[..., Any]]:
        return [self.plan_task, self.prepare_step, self.run_step, self.mark_needs_review,
                self.check_approval, self.set_paused, self.set_resumed, self.finish_task]


def wait_for(cond: Callable[[], bool], timeout: float) -> bool:  # pragma: no cover - helper
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False
