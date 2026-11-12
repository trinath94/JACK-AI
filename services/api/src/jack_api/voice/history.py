"""Voice conversation history with retention. Never stores audio."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select

from jack_api.db import Database, VoiceSession, VoiceTurn, utcnow


class VoiceHistory:
    def __init__(self, db: Database) -> None:
        self._db = db

    def start(self, trigger: str) -> str:
        with self._db.session() as s:
            vs = VoiceSession(trigger=trigger, started_at=utcnow())
            s.add(vs)
            s.flush()
            return vs.id

    def add_turn(self, session_id: str, role: str, text: str) -> None:
        with self._db.session() as s:
            s.add(VoiceTurn(session_id=session_id, role=role, text=text, created_at=utcnow()))

    def end(self, session_id: str, task_id: str | None = None) -> None:
        with self._db.session() as s:
            vs = s.get(VoiceSession, session_id)
            if vs is not None:
                vs.ended_at = utcnow()
                if task_id:
                    vs.task_id = task_id

    def list(self, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        with self._db.session() as s:
            total = s.scalar(select(func.count()).select_from(VoiceSession)) or 0
            sessions = s.scalars(select(VoiceSession).order_by(VoiceSession.started_at.desc())
                                 .limit(limit).offset(offset)).all()
            ids = [v.id for v in sessions]
            turns: dict[str, list[dict[str, Any]]] = {i: [] for i in ids}
            if ids:
                for t in s.scalars(select(VoiceTurn).where(VoiceTurn.session_id.in_(ids))
                                   .order_by(VoiceTurn.created_at)):
                    turns[t.session_id].append({"role": t.role, "text": t.text,
                                                "created_at": t.created_at.isoformat()})
            return [{"id": v.id, "trigger": v.trigger, "started_at": v.started_at.isoformat(),
                     "ended_at": v.ended_at.isoformat() if v.ended_at else None,
                     "task_id": v.task_id, "turns": turns[v.id]} for v in sessions], total

    def clear(self) -> int:
        with self._db.session() as s:
            n = s.scalar(select(func.count()).select_from(VoiceSession)) or 0
            s.execute(delete(VoiceTurn))
            s.execute(delete(VoiceSession))
            return n

    def purge(self, older_than_days: int) -> int:
        cutoff = utcnow() - timedelta(days=older_than_days)
        with self._db.session() as s:
            ids = list(s.scalars(select(VoiceSession.id).where(VoiceSession.started_at < cutoff)))
            if ids:
                s.execute(delete(VoiceTurn).where(VoiceTurn.session_id.in_(ids)))
                s.execute(delete(VoiceSession).where(VoiceSession.id.in_(ids)))
            return len(ids)
