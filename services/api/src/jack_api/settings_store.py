"""Typed key/value settings persisted in the ``settings`` table (non-secret values only)."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from jack_api.db import Database, Setting, utcnow

M = TypeVar("M", bound=BaseModel)


class SettingsStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str, model: type[M]) -> M:
        with self._db.session() as s:
            row = s.get(Setting, key)
            if row is None:
                return model()
            try:
                return model.model_validate(row.value)
            except ValidationError:
                # Stored value from an older schema: fall back to defaults rather than crash.
                return model()

    def put(self, key: str, value: BaseModel) -> None:
        data = value.model_dump(mode="json")
        with self._db.session() as s:
            row = s.get(Setting, key)
            if row is None:
                s.add(Setting(key=key, value=data, updated_at=utcnow()))
            else:
                row.value = data
                row.updated_at = utcnow()
