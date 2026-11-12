"""Loopback request authentication (threats T1–T3, T7).

Pure ASGI middleware (not BaseHTTPMiddleware) so it also covers WebSocket scopes.

Order of checks for HTTP:
1. Host header must be an allowed loopback host:port (DNS-rebinding defence) → 421.
2. CORS preflight (OPTIONS with Origin) passes through to the CORS middleware.
3. ``/health/live`` is public.
4. Everything else requires ``Authorization: Bearer <session token>`` → 401 + audit.

WebSockets: Host and Origin are checked here; the token is checked by the endpoint from
the first frame because browsers cannot set headers on WebSocket upgrades.
"""

from __future__ import annotations

import hmac
import json
import logging
import uuid
from collections.abc import Callable

import anyio
from starlette.types import ASGIApp, Receive, Scope, Send

from jack_api.audit import AuditLog
from jack_api.config import Settings

log = logging.getLogger(__name__)
PUBLIC_PATHS = frozenset({"/health/live"})


def token_matches(presented: str | None, expected: str) -> bool:
    if not presented:
        return False
    return hmac.compare_digest(presented.encode(), expected.encode())


def _header(scope: Scope, name: bytes) -> str | None:
    for k, v in scope.get("headers", []):
        if k == name:
            return str(v.decode("latin-1"))
    return None


async def _json_error(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps({"error": {"code": code, "message": message,
                                 "request_id": str(uuid.uuid4())}}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class LoopbackAuthMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings,
                 audit_factory: Callable[[], AuditLog | None]) -> None:
        self.app = app
        self.settings = settings
        self._token = settings.session_token.get_secret_value()
        self._audit_factory = audit_factory

    async def _audit_denied(self, scope: Scope, reason: str) -> None:
        audit = self._audit_factory()
        if audit is None:
            return
        client = scope.get("client")
        details = {"reason": reason, "method": scope.get("method", "WS"),
                   "client": f"{client[0]}:{client[1]}" if client else None,
                   "origin": _header(scope, b"origin")}
        try:
            await anyio.to_thread.run_sync(
                lambda: audit.record("api.auth", outcome="denied", actor_type="unknown",
                                     target=scope.get("path"), details=details))
        except Exception:  # noqa: BLE001 - auditing failure must not open the door
            log.exception("failed to write audit event for denied request")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        host = _header(scope, b"host")
        if host not in self.settings.allowed_hosts:
            await self._audit_denied(scope, "forbidden_host")
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 4403})
            else:
                await _json_error(send, 421, "forbidden_host", "Host header not allowed")
            return

        origin = _header(scope, b"origin")
        if scope["type"] == "websocket":
            if origin is not None and origin not in self.settings.allowed_origins:
                await self._audit_denied(scope, "origin_not_allowed")
                await send({"type": "websocket.close", "code": 4403})
                return
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if scope.get("method") == "OPTIONS" and origin is not None:
            await self.app(scope, receive, send)  # CORS preflight, handled by CORS middleware
            return
        if path in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        auth = _header(scope, b"authorization") or ""
        scheme, _, presented = auth.partition(" ")
        if scheme.lower() != "bearer" or not token_matches(presented.strip(), self._token):
            await self._audit_denied(scope, "missing_or_invalid_token")
            await _json_error(send, 401, "unauthorized", "Missing or invalid session token")
            return
        await self.app(scope, receive, send)
