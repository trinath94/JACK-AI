"""TaskWorkflow: the durable lifecycle of one task (Section 22).

Deterministic by construction: it holds only ids and flags, and every effect is an activity.
Temporal persists its history, so after a crash or a reboot the workflow continues exactly
where it was; completed steps are never redone.
"""

from __future__ import annotations

import asyncio
import builtins
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError, TimeoutError

TASK_QUEUE = "jack-tasks"
QUICK = RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=6)


def _cause_type(err: ActivityError) -> str:
    cause = err.cause
    if isinstance(cause, ApplicationError):
        return cause.type or "ApplicationError"
    if isinstance(cause, TimeoutError):
        return "Timeout"
    if isinstance(cause, CancelledError):
        return "Cancelled"
    return type(cause).__name__


@workflow.defn(name="TaskWorkflow")
class TaskWorkflow:
    def __init__(self) -> None:
        self.paused = False
        self.cancel_reason: str | None = None
        self.decided: set[str] = set()
        self.wake = 0      # any reason to look again: the user resumed, or the setup changed
        self.resumes = 0   # the user pressed Resume (only this clears "needs review")
        self.current: str | None = None
        self.phase = "starting"

    # ------------------------------------------------------------------ signals & queries
    @workflow.signal
    def pause(self) -> None:
        self.paused = True

    @workflow.signal
    def resume(self) -> None:
        self.paused = False
        self.wake += 1
        self.resumes += 1

    @workflow.signal
    def cancel(self, reason: str) -> None:
        self.cancel_reason = reason or "Cancelled"

    @workflow.signal
    def approval_decided(self, approval_id: str) -> None:
        # A hint only: the decision is re-read from JACK's database before it counts.
        self.decided.add(approval_id)

    @workflow.signal
    def capabilities_changed(self) -> None:
        self.wake += 1

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"phase": self.phase, "current_step": self.current, "paused": self.paused,
                "cancelling": self.cancel_reason is not None}

    # ------------------------------------------------------------------ helpers
    async def _act(self, name: str, *args: Any, timeout_s: int = 60) -> Any:
        return await workflow.execute_activity(
            name, args=list(args), start_to_close_timeout=timedelta(seconds=timeout_s),
            retry_policy=QUICK)

    async def _finish(self, task_id: str, outcome: str, reason: str) -> str:
        self.phase = outcome
        await self._act("finish_task", task_id, outcome, reason)
        return outcome

    def _decided_or_cancelled(self, aid: str) -> Callable[[], bool]:
        return lambda: aid in self.decided or self.cancel_reason is not None

    async def _wait_wake(self, since: int) -> None:
        """Wait for resume/capabilities_changed *after* ``since`` — a counter read before the
        check that found the step blocked, so a signal arriving in between isn't missed."""
        await workflow.wait_condition(
            lambda: self.wake != since or self.cancel_reason is not None)

    async def _wait_resume(self, since: int) -> None:
        """Wait for the user's Resume only (a setup change is not a review)."""
        await workflow.wait_condition(
            lambda: self.resumes != since or self.cancel_reason is not None)

    # ------------------------------------------------------------------ run
    @workflow.run
    async def run(self, task_id: str) -> str:
        self.phase = "planning"
        step_ids: list[str] = await self._act("plan_task", task_id)
        self.phase = "executing"
        for sid in step_ids:
            self.current = sid
            while True:
                if self.cancel_reason is not None:
                    return await self._finish(task_id, "cancelled", self.cancel_reason)
                if self.paused:
                    await self._act("set_paused", task_id, "Paused by you")
                    await workflow.wait_condition(
                        lambda: not self.paused or self.cancel_reason is not None)
                    if self.cancel_reason is None:
                        await self._act("set_resumed", task_id, True)
                    continue
                seen, seen_resumes = self.wake, self.resumes
                prep: dict[str, Any] = await self._act("prepare_step", task_id, sid)
                status = prep["status"]
                if status == "done":
                    break
                if status == "needs_review":
                    await self._wait_resume(seen_resumes)
                    if self.cancel_reason is None:
                        await self._act("set_resumed", task_id, True)
                    continue
                if status == "blocked":
                    await self._wait_wake(seen)
                    if self.cancel_reason is None:
                        await self._act("set_resumed", task_id,
                                        self.resumes != seen_resumes)
                    continue
                if status == "needs_approval":
                    aid: str = prep["approval_id"]
                    try:
                        await workflow.wait_condition(
                            self._decided_or_cancelled(aid),
                            timeout=timedelta(seconds=prep["expires_in_s"]))
                    except builtins.TimeoutError:
                        pass
                    if self.cancel_reason is not None:
                        continue
                    verdict = await self._act("check_approval", task_id, sid, aid)
                    if verdict == "approved":
                        continue
                    if verdict == "denied":
                        return await self._finish(task_id, "cancelled",
                                                  "You declined a required approval")
                    if verdict == "expired":
                        await self._wait_resume(seen_resumes)  # "Resume to ask again"
                    self.decided.discard(aid)  # "pending": the signal didn't match the record
                    continue
                if await self._run_step(task_id, sid, bool(prep.get("idempotent", True))):
                    break
                if self.phase == "failed":
                    return "failed"
        self.current = None
        return await self._finish(task_id, "completed", "")

    async def _run_step(self, task_id: str, sid: str, idempotent: bool) -> bool:
        """True when the step finished; False to re-evaluate it (blocked, review, cancel)."""
        retry = (RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2.0,
                             maximum_attempts=3,
                             non_retryable_error_types=["Blocked", "Cancelled",
                                                        "Interrupted"])
                 if idempotent else RetryPolicy(maximum_attempts=1))
        handle = workflow.start_activity(
            "run_step", args=[task_id, sid], start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(seconds=20), retry_policy=retry)
        await workflow.wait_condition(lambda: handle.done() or self.cancel_reason is not None)
        if not handle.done():
            handle.cancel()
            try:
                await handle
            except (ActivityError, asyncio.CancelledError):
                pass
            return False
        try:
            await handle
            return True
        except ActivityError as err:
            kind = _cause_type(err)
            if kind in ("Blocked", "Cancelled", "Interrupted"):
                return False
            if not idempotent:
                # Lost or failed mid-way and not safe to repeat: the user decides.
                await self._act("mark_needs_review", task_id, sid,
                                f"Interrupted ({kind}); not repeated automatically")
                return False
            self.phase = "failed"
            await self._act("finish_task", task_id, "failed",
                            f"A step failed after retries: {err.cause or err}")
            return False
