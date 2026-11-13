"""Approvals (Section 18/22): bound to one action, one target, a scope and an expiry.

Only the user decides, through the authenticated local API (a button, or a spoken "yes" while
JACK is asking). Each request carries a single-use nonce that the decision must echo, so a stale
screen or a replayed request can't decide a newer request. Workflows learn about decisions by
signal but re-read them here before acting (threat T28).
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select

from jack_api.audit import AuditLog
from jack_api.db import Approval, Database, utcnow

Decision = Literal["approve", "deny"]
Publisher = Callable[[str, dict[str, Any]], None]


class ApprovalError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def scope_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; they are stored as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class ApprovalService:
    def __init__(self, db: Database, audit: AuditLog, publish: Publisher) -> None:
        self._db = db
        self._audit = audit
        self._publish = publish
        self._listeners: list[Callable[[Approval], None]] = []

    def on_decided(self, fn: Callable[[Approval], None]) -> None:
        self._listeners.append(fn)

    def request(self, *, task_id: str, action: str, target: str, scope: dict[str, Any],
                summary: str, expires_in: timedelta, risk: str = "medium",
                step_id: str | None = None, requested_by: str = "jack") -> Approval:
        """Create (or return the still-pending) approval for exactly this action and scope."""
        with self._db.session() as s:
            existing = s.scalar(select(Approval).where(
                Approval.task_id == task_id, Approval.action == action,
                Approval.target == target, Approval.status == "pending"))
            if existing is not None:
                if existing.scope == scope and aware(existing.expires_at) > utcnow():
                    return existing
                existing.status = "withdrawn"  # scope changed: the old request no longer applies
            row = Approval(task_id=task_id, step_id=step_id, action=action, target=target,
                           scope=scope, summary=summary, risk=risk, status="pending",
                           nonce=secrets.token_urlsafe(24), requested_by=requested_by,
                           requested_at=utcnow(), expires_at=utcnow() + expires_in)
            s.add(row)
            s.flush()
        self._audit.record("approval.request", outcome="info", actor_type="system",
                           target=target, details={"approval": row.id, "action": action,
                                                   "expires_at": row.expires_at.isoformat()})
        self._publish("approval.updated", {"id": row.id, "task_id": task_id, "status": "pending"})
        return row

    def get(self, approval_id: str) -> Approval:
        with self._db.session() as s:
            row = s.get(Approval, approval_id)
            if row is None:
                raise ApprovalError("not_found", "Approval not found")
            self._expire(row)
            return row

    def list(self, status: str | None = None, task_id: str | None = None,
             limit: int = 50) -> list[Approval]:
        with self._db.session() as s:
            for row in s.scalars(select(Approval).where(Approval.status == "pending")):
                self._expire(row)
        with self._db.session() as s:
            q = select(Approval)
            if status:
                q = q.where(Approval.status == status)
            if task_id:
                q = q.where(Approval.task_id == task_id)
            return list(s.scalars(q.order_by(Approval.requested_at.desc()).limit(limit)))

    def decide(self, approval_id: str, decision: Decision, nonce: str, *, via: str,
               actor: str = "local-user") -> Approval:
        with self._db.session() as s:
            row = s.get(Approval, approval_id, with_for_update=True)
            if row is None:
                raise ApprovalError("not_found", "Approval not found")
            self._expire(row)
            if row.status != "pending":
                self._audit.record("approval.decide", outcome="denied", actor_type="user",
                                   target=row.target, details={"approval": row.id,
                                                               "reason": row.status})
                raise ApprovalError("not_pending", f"This approval is already {row.status}")
            if not secrets.compare_digest(nonce, row.nonce):
                self._audit.record("approval.decide", outcome="denied", actor_type="user",
                                   target=row.target, details={"approval": row.id,
                                                               "reason": "nonce"})
                raise ApprovalError("stale", "This approval request has changed; reload it")
            row.status = "approved" if decision == "approve" else "denied"
            row.decided_by = actor
            row.decided_via = via
            row.decided_at = utcnow()
            row.nonce = secrets.token_urlsafe(24)  # single use
        self._audit.record("approval.decide", outcome="allowed", actor_type="user",
                           actor_id=actor, target=row.target,
                           details={"approval": row.id, "action": row.action,
                                    "decision": row.status, "via": via})
        self._publish("approval.updated", {"id": row.id, "task_id": row.task_id,
                                           "status": row.status})
        for fn in self._listeners:
            fn(row)
        return row

    def withdraw_for_task(self, task_id: str) -> None:
        with self._db.session() as s:
            for row in s.scalars(select(Approval).where(Approval.task_id == task_id,
                                                        Approval.status == "pending")):
                row.status = "withdrawn"

    def _expire(self, row: Approval) -> None:
        if row.status == "pending" and aware(row.expires_at) <= utcnow():
            row.status = "expired"
            self._audit.record("approval.expire", outcome="info", actor_type="system",
                               target=row.target, details={"approval": row.id})


def approval_dict(a: Approval) -> dict[str, Any]:
    return {"id": a.id, "task_id": a.task_id, "step_id": a.step_id, "action": a.action,
            "target": a.target, "scope": a.scope, "summary": a.summary, "risk": a.risk,
            "status": a.status, "nonce": a.nonce if a.status == "pending" else None,
            "requested_by": a.requested_by, "requested_at": a.requested_at,
            "expires_at": a.expires_at, "decided_by": a.decided_by,
            "decided_via": a.decided_via, "decided_at": a.decided_at}
