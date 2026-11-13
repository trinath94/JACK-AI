"""Choosing and preparing JACK's databases (Milestone 6, decision D-1).

* ``main``: PostgreSQL (embedded by default) for tasks, audit and everything else; SQLite when
  PostgreSQL can't run here, with the reason surfaced in health and a notification.
* ``prefs``: SQLite ``prefs.db`` for local preferences (the ``settings`` table).

On the first PostgreSQL start, data from an earlier SQLite ``jack.db`` is moved across once,
verified (row counts and the audit hash chain), and the old file is kept as a backup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Table, func, insert, select, text

from jack_api.ai.credentials import CredentialStore
from jack_api.audit import AuditLog
from jack_api.config import Settings
from jack_api.db import Base, Database, Setting
from jack_api.embedded_pg import EmbeddedPostgres, PostgresUnavailable

log = logging.getLogger(__name__)

LEGACY_NAME = "jack.db"
SKIP_TABLES = {"settings", "alembic_version"}


@dataclass
class Stores:
    main: Database
    prefs: Database
    mode: str                 # postgres | sqlite | configured
    detail: str
    pg: EmbeddedPostgres | None = None
    migrated: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def close(self) -> None:
        self.main.dispose()
        self.prefs.dispose()
        if self.pg is not None:
            self.pg.stop()


def open_prefs(data_dir: Path) -> Database:
    prefs = Database(f"sqlite:///{(data_dir / 'prefs.db').as_posix()}")
    Setting.__table__.create(prefs.engine, checkfirst=True)  # type: ignore[attr-defined]
    return prefs


def open_stores(settings: Settings, creds: CredentialStore) -> Stores:
    data_dir = settings.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    prefs = open_prefs(data_dir)
    legacy = data_dir / LEGACY_NAME
    if settings.database_url:
        main = Database(settings.database_url)
        main.migrate()
        stores = Stores(main, prefs, "configured",
                        f"{main.backend} (JACK_DATABASE_URL)")
    elif settings.database == "sqlite":
        main = Database(f"sqlite:///{legacy.as_posix()}")
        main.migrate()
        stores = Stores(main, prefs, "sqlite", "SQLite (chosen in configuration)")
    else:
        stores = _open_embedded(settings, creds, prefs, legacy)
    _adopt_legacy_settings(stores.main, prefs)
    return stores


def _open_embedded(settings: Settings, creds: CredentialStore, prefs: Database,
                   legacy: Path) -> Stores:
    pg = EmbeddedPostgres(settings.data_dir, creds, logs_dir=settings.log_dir)
    try:
        url = pg.start()
        main = Database(url)
        main.migrate()
        stores = Stores(main, prefs, "postgres", pg.status().detail, pg=pg)
        if legacy.exists():
            _move_legacy(legacy, stores)
        return stores
    except Exception as exc:  # noqa: BLE001 - any failure: run on SQLite and say why
        reason = str(exc) if isinstance(exc, PostgresUnavailable) else \
            f"{type(exc).__name__}: {exc}"
        log.warning("embedded PostgreSQL unavailable, using SQLite: %s", reason)
        pg.stop()
        main = Database(f"sqlite:///{legacy.as_posix()}")
        main.migrate()
        return Stores(main, prefs, "sqlite", f"SQLite fallback — PostgreSQL: {reason}",
                      warnings=[f"JACK is using SQLite because PostgreSQL couldn't start: "
                                f"{reason}"])


def _move_legacy(legacy: Path, stores: Stores) -> None:
    """Copy an existing SQLite database into the (empty) PostgreSQL one, once."""
    src = Database(f"sqlite:///{legacy.as_posix()}")
    dst = stores.main
    try:
        src.migrate()  # bring the old file to the same schema first
        with dst.session() as s:
            existing = s.scalar(text("select count(*) from audit_events")) or 0
        if existing:
            stores.warnings.append(
                f"An older SQLite database ({legacy.name}) was found but PostgreSQL already "
                "has data, so it was not merged. It is kept unchanged.")
            return
        counts = _copy_all(src, dst, stores.prefs)
        result = AuditLog(dst).verify()
        if not result.valid:
            raise RuntimeError(f"audit chain broken after copy at #{result.first_invalid_seq}")
    except Exception:
        _wipe(dst)
        raise
    finally:
        src.dispose()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    for suffix in ("", "-wal", "-shm"):
        f = legacy.with_name(legacy.name + suffix)
        if f.exists():
            f.rename(f.with_name(f"{legacy.name}.pre-postgres-{stamp}{suffix}"))
    stores.migrated = counts
    AuditLog(dst).record("database.migrate", outcome="allowed", actor_type="system",
                         details={"from": "sqlite", "to": "postgresql", "rows": counts,
                                  "backup": f"{legacy.name}.pre-postgres-{stamp}"})
    log.info("moved %d rows from SQLite to PostgreSQL", sum(counts.values()))


def _copy_all(src: Database, dst: Database, prefs: Database) -> dict[str, int]:
    counts: dict[str, int] = {}
    tables = [t for t in Base.metadata.sorted_tables if t.name not in SKIP_TABLES]
    with src.engine.connect() as sc, dst.engine.begin() as dc:
        for table in tables:
            n = 0
            batch: list[dict[str, Any]] = []
            for row in sc.execute(select(table)).mappings():
                batch.append(_utc(table, dict(row)))
                if len(batch) >= 500:
                    dc.execute(insert(table), batch)
                    n += len(batch)
                    batch = []
            if batch:
                dc.execute(insert(table), batch)
                n += len(batch)
            got = dc.execute(select(func.count()).select_from(table)).scalar_one()
            if got != n:
                raise RuntimeError(f"{table.name}: copied {n} rows but found {got}")
            counts[table.name] = n
        rows = [dict(r) for r in sc.execute(select(Setting.__table__)).mappings()]
    with prefs.session() as ps:
        for r in rows:
            if ps.get(Setting, r["key"]) is None:
                ps.add(Setting(key=r["key"], value=r["value"],
                               updated_at=_aware(r["updated_at"])))
    counts["settings"] = len(rows)
    return counts


def _utc(table: Table, row: dict[str, Any]) -> dict[str, Any]:
    # SQLite returns naive datetimes that were written as UTC; make that explicit for PostgreSQL.
    for k, v in row.items():
        if isinstance(v, datetime) and v.tzinfo is None:
            row[k] = v.replace(tzinfo=UTC)
    return row


def _aware(v: Any) -> Any:
    return v.replace(tzinfo=UTC) if isinstance(v, datetime) and v.tzinfo is None else v


def _wipe(db: Database) -> None:
    """Undo a partial move: leave PostgreSQL empty (schema at head, no rows)."""
    try:
        with db.engine.begin() as c:
            for table in reversed(Base.metadata.sorted_tables):
                if table.name not in SKIP_TABLES:
                    c.execute(table.delete())
    except Exception:  # noqa: BLE001
        log.exception("could not clean up after a failed move")


def _adopt_legacy_settings(main: Database, prefs: Database) -> None:
    """Preferences written to the main database by M1–M5 move to prefs.db once."""
    with prefs.session() as ps:
        if ps.scalar(select(func.count()).select_from(Setting)):
            return
    try:
        with main.session() as ms:
            rows = list(ms.scalars(select(Setting)))
            data = [(r.key, r.value, r.updated_at) for r in rows]
    except Exception:  # noqa: BLE001 - no settings table there
        return
    if not data:
        return
    with prefs.session() as ps:
        for key, value, updated in data:
            ps.add(Setting(key=key, value=value, updated_at=_aware(updated)))
