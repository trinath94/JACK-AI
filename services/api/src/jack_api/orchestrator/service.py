"""Orchestrator: owns the Temporal server, the worker, and the task ⇄ workflow mapping."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import logging
from collections.abc import Coroutine
from typing import Any

from sqlalchemy import select
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError
from temporalio.worker import Worker

from jack_api.db import Approval, Task, TaskStep, WorkflowRun, utcnow
from jack_api.orchestrator.activities import Activities, Deps
from jack_api.orchestrator.workflows import TASK_QUEUE, TaskWorkflow
from jack_api.tasks import TERMINAL, TaskStatus, move_to
from jack_api.temporal_server import TemporalServer, TemporalUnavailable

log = logging.getLogger(__name__)
S = TaskStatus
CLOSE_WAIT_S = 30


def workflow_id(task_id: str) -> str:
    return f"task-{task_id}"


class OrchestratorUnavailable(Exception):
    pass


class Orchestrator:
    def __init__(self, deps: Deps, server: TemporalServer | None) -> None:
        self.d = deps
        self.server = server
        self.client: Client | None = None
        self._worker: Worker | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=8,
                                                           thread_name_prefix="activity")
        self.detail = "not started"
        self.recovered: dict[str, int] = {}

    # ------------------------------------------------------------------ lifecycle
    def start_server(self) -> None:
        """Synchronous, on the main thread (parent-death signal on Linux)."""
        if self.server is None:
            raise TemporalUnavailable("Temporal is turned off")
        self.server.start()

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self.server is None or not self.server.running():
            raise TemporalUnavailable(self.detail)
        self.client = await self._connect(self.server.target)
        acts = Activities(self.d)
        self._worker = Worker(self.client, task_queue=TASK_QUEUE, workflows=[TaskWorkflow],
                              activities=acts.all(), activity_executor=self._pool,
                              max_concurrent_activities=8)
        self._worker_task = asyncio.create_task(self._worker.run())
        self.detail = f"Temporal on {self.server.target}"
        self.recovered = await self.reconcile()

    async def _connect(self, target: str) -> Client:
        last: Exception | None = None
        for _ in range(50):  # the namespace appears a moment after the port opens
            try:
                c = await Client.connect(target, namespace="default")
                await c.count_workflows()
                return c
            except Exception as exc:  # noqa: BLE001
                last = exc
                await asyncio.sleep(0.2)
        raise TemporalUnavailable(f"could not connect to Temporal: {last}")

    async def stop(self) -> None:
        if self._worker is not None:
            try:
                await asyncio.wait_for(self._worker.shutdown(), timeout=10)
            except TimeoutError:
                log.warning("worker shutdown timed out")
        if self._worker_task is not None:
            self._worker_task.cancel()
        self._pool.shutdown(wait=False, cancel_futures=True)
        if self.server is not None:
            await asyncio.to_thread(self.server.stop)

    @property
    def ready(self) -> bool:
        return self.client is not None and self._worker_task is not None and \
            not self._worker_task.done()

    # ------------------------------------------------------------------ sync bridge
    def _run(self, coro: Coroutine[Any, Any, Any], timeout: float = 30) -> Any:
        """Run on the service loop from a worker/voice thread."""
        if self._loop is None or not self.ready:
            coro.close()
            raise OrchestratorUnavailable("Task orchestration isn't running: " + self.detail)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            raise RuntimeError("use the async methods on the service loop")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    # ------------------------------------------------------------------ task operations
    def start_task(self, task_id: str) -> None:
        self._run(self.astart_task(task_id))

    async def astart_task(self, task_id: str) -> None:
        assert self.client is not None
        for attempt in range(2):
            try:
                handle = await self.client.start_workflow(
                    TaskWorkflow.run, task_id, id=workflow_id(task_id), task_queue=TASK_QUEUE,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE)
                break
            except WorkflowAlreadyStartedError:
                if attempt:
                    raise
                # The previous run marks the task finished from its last activity, a moment
                # before the run itself closes. A quick Retry lands in that gap: wait for it.
                old = self.client.get_workflow_handle(workflow_id(task_id))
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(old.result(), timeout=CLOSE_WAIT_S)
        await asyncio.to_thread(self._record_run, task_id, handle.result_run_id or "")
        self.d.audit.record("task.workflow.start", outcome="info", actor_type="system",
                            target=f"task:{task_id}", details={"workflow": handle.id})

    def _record_run(self, task_id: str, run_id: str) -> None:
        with self.d.db.session() as s:
            s.add(WorkflowRun(task_id=task_id, workflow_id=workflow_id(task_id), run_id=run_id,
                              status="running", started_at=utcnow()))

    def has_workflow(self, task_id: str) -> bool:
        with self.d.db.session() as s:
            return s.scalar(select(WorkflowRun.id).where(WorkflowRun.task_id == task_id,
                                                         WorkflowRun.status == "running")) \
                is not None

    def signal(self, task_id: str, name: str, *args: Any) -> None:
        self._run(self.asignal(task_id, name, *args))

    async def asignal(self, task_id: str, name: str, *args: Any) -> None:
        assert self.client is not None
        h = self.client.get_workflow_handle(workflow_id(task_id))
        await h.signal(name, *args)

    def pause(self, task_id: str) -> None:
        self.signal(task_id, "pause")
        self.d.audit.record("task.pause", outcome="allowed", actor_type="user",
                            target=f"task:{task_id}")

    def resume(self, task_id: str) -> None:
        self.signal(task_id, "resume")
        self.d.audit.record("task.resume", outcome="allowed", actor_type="user",
                            target=f"task:{task_id}")

    def cancel(self, task_id: str, reason: str) -> None:
        self.signal(task_id, "cancel", reason or "Cancelled by you")
        self.d.audit.record("task.cancel", outcome="allowed", actor_type="user",
                            target=f"task:{task_id}")

    def retry(self, task_id: str) -> None:
        task, _ = self.d.tasks.get(task_id)
        if task.status != S.FAILED:
            raise ValueError("Only failed tasks can be retried")
        with self.d.db.session() as s:
            for st in s.scalars(select(TaskStep).where(TaskStep.task_id == task_id,
                                                       TaskStep.status.in_(("failed",
                                                                            "running")))):
                st.status = "pending"
                st.updated_at = utcnow()
        move_to(self.d.tasks, task_id, S.PLANNING, "Retry: continuing from the first "
                "unfinished step", "local-user", self.d.publish_task)
        self.d.audit.record("task.retry", outcome="allowed", actor_type="user",
                            target=f"task:{task_id}")
        self.start_task(task_id)

    def approval_decided(self, approval: Approval) -> None:
        """Tell the task's workflow to re-check (it reads the decision from the database)."""
        if approval.step_id and self.has_workflow(approval.task_id):
            self.signal(approval.task_id, "approval_decided", approval.id)

    def capabilities_changed(self) -> None:
        with self.d.db.session() as s:
            ids = [r.task_id for r in s.scalars(select(WorkflowRun)
                                                .where(WorkflowRun.status == "running"))]
        for tid in ids:
            try:
                self.signal(tid, "capabilities_changed")
            except Exception:  # noqa: BLE001
                log.exception("could not signal task %s", tid)

    # ------------------------------------------------------------------ recovery
    async def reconcile(self) -> dict[str, int]:
        """After a restart: running workflows continue by themselves; tasks whose workflow is
        missing need review; tasks that reached planning without one get one now."""
        assert self.client is not None
        counts = {"resumed": 0, "started": 0, "needs_review": 0}

        def load() -> tuple[list[tuple[str, str]], list[str]]:
            with self.d.db.session() as s:
                runs = [(r.task_id, r.workflow_id) for r in s.scalars(
                    select(WorkflowRun).where(WorkflowRun.status == "running"))]
                tracked = {t for t, _ in runs}
                planning = [t.id for t in s.scalars(select(Task).where(
                    Task.status == S.PLANNING)) if t.id not in tracked]
            return runs, planning

        runs, planning = await asyncio.to_thread(load)
        for task_id, wid in runs:
            try:
                desc = await self.client.get_workflow_handle(wid).describe()
                if desc.status == WorkflowExecutionStatus.RUNNING:
                    counts["resumed"] += 1
                    continue
                state = desc.status.name if desc.status else "unknown"
            except RPCError:
                state = "missing"
            await asyncio.to_thread(self._needs_review, task_id, state)
            counts["needs_review"] += 1
        for task_id in planning:
            await self.astart_task(task_id)
            counts["started"] += 1
        if any(counts.values()):
            parts = []
            if counts["resumed"]:
                parts.append(f"{counts['resumed']} task(s) resumed where they left off")
            if counts["started"]:
                parts.append(f"{counts['started']} waiting task(s) started")
            if counts["needs_review"]:
                parts.append(f"{counts['needs_review']} task(s) need your review")
            self.d.notes.create("task.recovered", "JACK recovered your tasks",
                                "; ".join(parts) + ".",
                                level="warning" if counts["needs_review"] else "info")
            self.d.audit.record("task.recover", outcome="info", actor_type="system",
                                details=counts)
        return counts

    def _needs_review(self, task_id: str, state: str) -> None:
        with self.d.db.session() as s:
            for r in s.scalars(select(WorkflowRun).where(WorkflowRun.task_id == task_id,
                                                         WorkflowRun.status == "running")):
                r.status = "lost"
                r.ended_at = utcnow()
        task, _ = self.d.tasks.get(task_id)
        if task.status not in TERMINAL:
            move_to(self.d.tasks, task_id, S.WAITING_FOR_INFORMATION,
                    f"JACK couldn't find this task's progress after restarting (workflow "
                    f"{state.lower()}). Retry or cancel it.", "jack", self.d.publish_task)


def orchestrator_status(o: Orchestrator | None) -> tuple[str, str]:
    if o is None:
        return "degraded", "Task orchestration is off"
    if not o.ready:
        return "degraded", o.detail
    if o.server is not None and not o.server.running():
        return "unhealthy", "The Temporal server stopped"
    return "healthy", o.detail
