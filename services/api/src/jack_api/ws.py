"""WebSocket hub: authenticated real-time events (API_CONTRACTS.md §3)."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)


def envelope(topic: str, data: Any) -> str:
    return json.dumps(
        {"type": "event", "topic": topic, "ts": datetime.now(UTC).isoformat(), "data": data},
        default=str,
    )


class Hub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self.loop: asyncio.AbstractEventLoop | None = None

    @property
    def count(self) -> int:
        return len(self._clients)

    async def add(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, topic: str, data: Any) -> None:
        message = envelope(topic, data)
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_text(message)
            except Exception:  # noqa: BLE001 - drop dead connections
                await self.remove(ws)

    def publish_threadsafe(self, topic: str, data: Any) -> None:
        """Broadcast from synchronous (threadpool) route handlers."""
        if self.loop is None or self.loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(topic, data), self.loop)
