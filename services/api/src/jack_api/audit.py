"""Append-only, hash-chained audit log (threats T8, T22).

hash_n = SHA-256(prev_hash || canonical JSON of the row's content fields).
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select

from jack_api.db import AuditEvent, Database, utcnow
from jack_api.redaction import redact

GENESIS = "0" * 64
ActorType = Literal["user", "agent", "system", "unknown"]
Outcome = Literal["allowed", "denied", "error", "info"]


def _canonical(fields: dict[str, Any]) -> str:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)


def _ts(dt: datetime) -> str:
    # SQLite drops tzinfo on round trip; normalise to naive-UTC ISO for hashing.
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.isoformat(timespec="microseconds")


def compute_hash(prev_hash: str, row: AuditEvent) -> str:
    content = {
        "seq": row.seq,
        "occurred_at": _ts(row.occurred_at),
        "actor_type": row.actor_type,
        "actor_id": row.actor_id,
        "action": row.action,
        "target": row.target,
        "outcome": row.outcome,
        "details": row.details,
    }
    return hashlib.sha256((prev_hash + _canonical(content)).encode()).hexdigest()


@dataclass(frozen=True)
class VerifyResult:
    valid: bool
    checked: int
    first_invalid_seq: int | None


class AuditLog:
    def __init__(self, db: Database) -> None:
        self._db = db
        # Single-writer chain within this process; the service is the only writer.
        self._lock = threading.Lock()

    def record(
        self,
        action: str,
        *,
        outcome: Outcome,
        actor_type: ActorType = "system",
        actor_id: str | None = None,
        target: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        safe_details = json.loads(redact(_canonical(details or {})))
        with self._lock, self._db.session() as s:
            last = s.execute(
                select(AuditEvent.seq, AuditEvent.hash).order_by(AuditEvent.seq.desc()).limit(1)
            ).first()
            seq, prev = (last[0] + 1, last[1]) if last else (1, GENESIS)
            row = AuditEvent(
                seq=seq,
                occurred_at=utcnow(),
                actor_type=actor_type,
                actor_id=actor_id,
                action=action,
                target=redact(target) if target else None,
                outcome=outcome,
                details=safe_details,
                prev_hash=prev,
                hash="",
            )
            row.hash = compute_hash(prev, row)
            s.add(row)
        return row

    def list(self, limit: int, offset: int) -> tuple[list[AuditEvent], int]:
        with self._db.session() as s:
            total = s.scalar(select(func.count()).select_from(AuditEvent)) or 0
            rows = s.scalars(
                select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(limit).offset(offset)
            ).all()
            return list(rows), total

    def verify(self) -> VerifyResult:
        prev = GENESIS
        checked = 0
        expected_seq = 1
        with self._db.session() as s:
            for row in s.scalars(select(AuditEvent).order_by(AuditEvent.seq)).yield_per(500):
                checked += 1
                if (
                    row.seq != expected_seq
                    or row.prev_hash != prev
                    or row.hash != compute_hash(prev, row)
                ):
                    return VerifyResult(False, checked, row.seq)
                prev = row.hash
                expected_seq += 1
        return VerifyResult(True, checked, None)
