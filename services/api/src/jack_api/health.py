"""Health registry: every internal component registers a probe (Section 3)."""

from __future__ import annotations

import asyncio
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import text

from jack_api.db import Database

Status = Literal["healthy", "degraded", "unhealthy"]
_RANK: dict[Status, int] = {"healthy": 0, "degraded": 1, "unhealthy": 2}
PROBE_TIMEOUT_S = 2.0


@dataclass
class ProbeResult:
    status: Status
    detail: str | None = None


@dataclass
class ComponentHealth:
    name: str
    status: Status
    detail: str | None
    latency_ms: float
    checked_at: str


Probe = Callable[[], Awaitable[ProbeResult]]


class HealthRegistry:
    def __init__(self) -> None:
        self._probes: dict[str, Probe] = {}
        self._last: dict[str, ComponentHealth] = {}

    def register(self, name: str, probe: Probe) -> None:
        self._probes[name] = probe

    async def _run(self, name: str, probe: Probe) -> ComponentHealth:
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(probe(), PROBE_TIMEOUT_S)
        except TimeoutError:
            result = ProbeResult("unhealthy", f"probe timed out after {PROBE_TIMEOUT_S}s")
        except Exception as exc:  # noqa: BLE001 - a failing probe is a health signal
            result = ProbeResult("unhealthy", f"{type(exc).__name__}: {exc}")
        return ComponentHealth(
            name=name,
            status=result.status,
            detail=result.detail,
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
            checked_at=datetime.now(UTC).isoformat(),
        )

    async def check(self) -> tuple[list[ComponentHealth], bool]:
        """Run all probes concurrently. Returns (results, changed_since_last_check)."""
        results = await asyncio.gather(*(self._run(n, p) for n, p in self._probes.items()))
        changed = any(
            self._last.get(r.name) is None or self._last[r.name].status != r.status
            for r in results
        )
        self._last = {r.name: r for r in results}
        return list(results), changed

    @staticmethod
    def overall(results: list[ComponentHealth]) -> Status:
        worst: Status = "healthy"
        for r in results:
            if _RANK[r.status] > _RANK[worst]:
                worst = r.status
        return worst

    @staticmethod
    def as_dicts(results: list[ComponentHealth]) -> list[dict[str, Any]]:
        return [asdict(r) for r in results]


def database_probe(db: Database, stores: Any = None) -> Probe:
    async def probe() -> ProbeResult:
        def ping() -> None:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT 1"))

        await asyncio.to_thread(ping)
        if stores is None:
            return ProbeResult("healthy", db.backend)
        if stores.pg is not None and not stores.pg.status().running:
            return ProbeResult("unhealthy", stores.pg.status().detail)
        # Running on SQLite because PostgreSQL couldn't start is a degraded state, not hidden.
        if stores.mode == "sqlite" and stores.warnings:
            return ProbeResult("degraded", stores.detail)
        return ProbeResult("healthy", stores.detail)

    return probe


def disk_probe(path: Path, degraded_below_bytes: int = 1 << 30) -> Probe:
    async def probe() -> ProbeResult:
        usage = await asyncio.to_thread(shutil.disk_usage, path)
        free_gb = usage.free / (1 << 30)
        if usage.free < degraded_below_bytes // 4:
            return ProbeResult("unhealthy", f"{free_gb:.2f} GiB free")
        if usage.free < degraded_below_bytes:
            return ProbeResult("degraded", f"{free_gb:.2f} GiB free")
        return ProbeResult("healthy", f"{free_gb:.1f} GiB free")

    return probe


async def api_probe() -> ProbeResult:
    return ProbeResult("healthy")
