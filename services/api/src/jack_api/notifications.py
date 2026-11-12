"""Notification centre: durable user-facing notifications pushed over WebSocket."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from sqlalchemy import func, select, update

from jack_api.db import Database, Notification, utcnow

Level = Literal["info", "success", "warning", "error"]
Publisher = Callable[[str, Any], None]


def to_dict(n: Notification) -> dict[str, Any]:
    return {
        "id": n.id,
        "level": n.level,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "task_id": n.task_id,
        "created_at": n.created_at.isoformat(),
        "read_at": n.read_at.isoformat() if n.read_at else None,
    }


class NotificationCentre:
    def __init__(self, db: Database, publish: Publisher) -> None:
        self._db = db
        self._publish = publish

    def create(self, kind: str, title: str, body: str | None = None, *,
               level: Level = "info", task_id: str | None = None) -> Notification:
        n = Notification(kind=kind, title=title[:255], body=body, level=level, task_id=task_id,
                         created_at=utcnow())
        with self._db.session() as s:
            s.add(n)
        self._publish("notification.created", to_dict(n))
        return n

    def list(self, unread_only: bool, limit: int, offset: int
             ) -> tuple[list[Notification], int, int]:
        with self._db.session() as s:
            q = select(Notification)
            if unread_only:
                q = q.where(Notification.read_at.is_(None))
            total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
            unread = s.scalar(select(func.count()).select_from(Notification)
                              .where(Notification.read_at.is_(None))) or 0
            rows = s.scalars(q.order_by(Notification.created_at.desc())
                             .limit(limit).offset(offset)).all()
            return list(rows), total, unread

    def mark_read(self, notification_id: str) -> bool:
        with self._db.session() as s:
            n = s.get(Notification, notification_id)
            if n is None:
                return False
            if n.read_at is None:
                n.read_at = utcnow()
        self._publish("notification.read", {"ids": [notification_id]})
        return True

    def mark_all_read(self) -> int:
        with self._db.session() as s:
            ids = list(s.scalars(select(Notification.id).where(Notification.read_at.is_(None))))
            if ids:
                s.execute(update(Notification).where(Notification.id.in_(ids))
                          .values(read_at=utcnow()))
        if ids:
            self._publish("notification.read", {"ids": ids})
        return len(ids)
