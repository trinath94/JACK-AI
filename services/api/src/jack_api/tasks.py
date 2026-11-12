"""Durable task store and lifecycle state machine (Section 22).

Every transition is validated against ``ALLOWED`` and recorded in ``task_events`` and the
audit log. Execution of tasks is not part of Milestone 1; this module is the persistence
contract the orchestrator (M6) builds on.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import func, select

from jack_api.audit import AuditLog
from jack_api.db import Database, Task, TaskEvent, utcnow


class TaskStatus(StrEnum):
    RECEIVED = "RECEIVED"
    UNDERSTANDING = "UNDERSTANDING"
    REQUIREMENTS = "REQUIREMENTS"
    PLANNING = "PLANNING"
    APPROVAL = "APPROVAL"
    EXECUTION = "EXECUTION"
    TESTING = "TESTING"
    REPAIR = "REPAIR"
    RELEASE_PREPARATION = "RELEASE_PREPARATION"
    DEPLOYMENT_APPROVAL = "DEPLOYMENT_APPROVAL"
    DEPLOYMENT = "DEPLOYMENT"
    VERIFICATION = "VERIFICATION"
    COMPLETED = "COMPLETED"
    WAITING_FOR_INFORMATION = "WAITING_FOR_INFORMATION"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


S = TaskStatus
TERMINAL = frozenset({S.COMPLETED, S.CANCELLED, S.FAILED, S.ROLLED_BACK})
HOLD = frozenset({S.WAITING_FOR_INFORMATION, S.WAITING_FOR_APPROVAL, S.PAUSED})
ACTIVE = frozenset(S) - TERMINAL - HOLD

_FORWARD: dict[TaskStatus, set[TaskStatus]] = {
    S.RECEIVED: {S.UNDERSTANDING},
    S.UNDERSTANDING: {S.REQUIREMENTS, S.PLANNING},
    S.REQUIREMENTS: {S.PLANNING},
    S.PLANNING: {S.APPROVAL, S.EXECUTION},
    S.APPROVAL: {S.EXECUTION},
    S.EXECUTION: {S.TESTING, S.COMPLETED},
    S.TESTING: {S.REPAIR, S.RELEASE_PREPARATION, S.COMPLETED},
    S.REPAIR: {S.TESTING},
    S.RELEASE_PREPARATION: {S.DEPLOYMENT_APPROVAL, S.COMPLETED},
    S.DEPLOYMENT_APPROVAL: {S.DEPLOYMENT},
    S.DEPLOYMENT: {S.VERIFICATION, S.ROLLED_BACK},
    S.VERIFICATION: {S.COMPLETED, S.ROLLED_BACK},
}


def allowed_targets(current: TaskStatus, resume_status: TaskStatus | None) -> set[TaskStatus]:
    if current in TERMINAL:
        return {S.RECEIVED} if current is S.FAILED else set()
    if current in HOLD:
        targets: set[TaskStatus] = {S.CANCELLED, S.FAILED}
        if resume_status is not None:
            targets.add(resume_status)
        return targets
    return _FORWARD.get(current, set()) | set(HOLD) | {S.CANCELLED, S.FAILED}


class InvalidTransition(Exception):
    def __init__(self, current: TaskStatus, target: TaskStatus) -> None:
        super().__init__(f"Cannot move task from {current} to {target}")
        self.current = current
        self.target = target


class TaskNotFound(Exception):
    pass


class TaskStore:
    def __init__(self, db: Database, audit: AuditLog) -> None:
        self._db = db
        self._audit = audit

    def create(self, command_text: str, source: str, title: str | None, actor: str) -> Task:
        now = utcnow()
        clean = " ".join(command_text.split())
        task = Task(
            title=(title or clean[:80]).strip() or "Untitled task",
            command_text=command_text,
            source=source,
            status=S.RECEIVED,
            created_at=now,
            updated_at=now,
        )
        with self._db.session() as s:
            s.add(task)
            s.flush()
            s.add(TaskEvent(task_id=task.id, seq=1, from_status=None, to_status=S.RECEIVED,
                            reason="created", actor=actor, occurred_at=now))
        self._audit.record("task.create", outcome="allowed", actor_type="user",
                           actor_id=actor, target=f"task:{task.id}", details={"source": source})
        return task

    def get(self, task_id: str) -> tuple[Task, list[TaskEvent]]:
        with self._db.session() as s:
            task = s.get(Task, task_id)
            if task is None:
                raise TaskNotFound(task_id)
            events = s.scalars(
                select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.seq)
            ).all()
            return task, list(events)

    def list(self, status: TaskStatus | None, limit: int, offset: int) -> tuple[list[Task], int]:
        with self._db.session() as s:
            q = select(Task)
            cq = select(func.count()).select_from(Task)
            if status is not None:
                q = q.where(Task.status == status)
                cq = cq.where(Task.status == status)
            total = s.scalar(cq) or 0
            rows = s.scalars(q.order_by(Task.updated_at.desc()).limit(limit).offset(offset)).all()
            return list(rows), total

    def transition(self, task_id: str, target: TaskStatus, reason: str | None, actor: str) -> Task:
        with self._db.session() as s:
            task = s.get(Task, task_id, with_for_update=True)
            if task is None:
                raise TaskNotFound(task_id)
            current = TaskStatus(task.status)
            resume = TaskStatus(task.resume_status) if task.resume_status else None
            if target not in allowed_targets(current, resume):
                self._audit.record("task.transition", outcome="denied", actor_type="user",
                                   actor_id=actor, target=f"task:{task_id}",
                                   details={"from": current, "to": target})
                raise InvalidTransition(current, target)
            now = utcnow()
            if target in HOLD and current in ACTIVE:
                task.resume_status = current
            elif current in HOLD and target not in HOLD:
                task.resume_status = None
            task.status = target
            task.status_reason = reason
            task.updated_at = now
            if target in TERMINAL:
                task.completed_at = now
            elif target is S.RECEIVED:
                task.completed_at = None
            next_seq = (s.scalar(select(func.max(TaskEvent.seq))
                                 .where(TaskEvent.task_id == task_id)) or 0) + 1
            s.add(TaskEvent(task_id=task_id, seq=next_seq, from_status=current, to_status=target,
                            reason=reason, actor=actor, occurred_at=now))
        self._audit.record("task.transition", outcome="allowed", actor_type="user",
                           actor_id=actor, target=f"task:{task_id}",
                           details={"from": current, "to": target})
        return task

    def resume(self, task_id: str, reason: str | None, actor: str) -> Task:
        task, _ = self.get(task_id)
        if task.status not in HOLD or not task.resume_status:
            raise InvalidTransition(TaskStatus(task.status), TaskStatus(task.status))
        return self.transition(task_id, TaskStatus(task.resume_status), reason, actor)
