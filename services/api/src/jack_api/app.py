"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import platform
import socket
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from jack_api import schemas
from jack_api.audit import AuditLog
from jack_api.config import VERSION, Settings
from jack_api.db import Database, Device, utcnow
from jack_api.health import (
    HealthRegistry,
    ProbeResult,
    api_probe,
    database_probe,
    disk_probe,
)
from jack_api.metrics import SystemMetrics
from jack_api.notifications import NotificationCentre
from jack_api.redaction import register_secret
from jack_api.routes_m2 import router as m2_router
from jack_api.security import LoopbackAuthMiddleware, token_matches
from jack_api.settings_store import SettingsStore
from jack_api.tasks import InvalidTransition, TaskNotFound, TaskStatus, TaskStore
from jack_api.voice.audio import AudioBackend, SoundDeviceBackend
from jack_api.voice.engine import VoiceBlocked, VoiceEngine
from jack_api.ws import Hub, envelope

log = logging.getLogger(__name__)
LOCAL_USER = "local-user"  # single-user desktop; replaced by authenticated users in M6


@dataclass
class Services:
    settings: Settings
    db: Database
    audit: AuditLog
    tasks: TaskStore
    health: HealthRegistry
    hub: Hub
    started_at: float
    store: SettingsStore
    notifications: NotificationCentre
    voice: VoiceEngine
    metrics: SystemMetrics


# Task states that deserve a notification (Section 22 alternative/terminal states).
NOTIFY_TASK_STATES: dict[str, tuple[str, str]] = {
    "COMPLETED": ("success", "Task completed"),
    "FAILED": ("error", "Task failed"),
    "CANCELLED": ("info", "Task cancelled"),
    "ROLLED_BACK": ("warning", "Task rolled back"),
    "WAITING_FOR_INFORMATION": ("warning", "JACK needs information"),
    "WAITING_FOR_APPROVAL": ("warning", "Approval required"),
}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message, "request_id": None}})


def _register_device(db: Database) -> None:
    name = socket.gethostname()
    with db.session() as s:
        dev = s.scalars(select(Device).where(Device.name == name)).first()
        if dev is None:
            s.add(Device(name=name, os_version=platform.platform(), app_version=VERSION))
        else:
            dev.last_seen_at = utcnow()
            dev.os_version = platform.platform()
            dev.app_version = VERSION


async def _health_loop(svc: Services) -> None:
    previous: dict[str, str] = {}
    while True:
        results, changed = await svc.health.check()
        if changed:
            await svc.hub.broadcast("health.changed", {
                "status": svc.health.overall(results),
                "components": svc.health.as_dicts(results),
            })
            for r in results:
                before = previous.get(r.name)
                if before is None or before == r.status:
                    continue  # first observation or no change: not news
                if r.status == "healthy":
                    level, title = "success", f"{r.name.capitalize()} recovered"
                else:
                    level = "error" if r.status == "unhealthy" else "warning"
                    title = f"{r.name.capitalize()} is {r.status}"
                await asyncio.to_thread(svc.notifications.create, "health", title, r.detail,
                                        level=level)  # type: ignore[arg-type]
        previous = {r.name: r.status for r in results}
        await asyncio.sleep(svc.settings.health_interval_s)


async def _metrics_loop(svc: Services) -> None:
    while True:
        if svc.hub.count:
            await svc.hub.broadcast("system.metrics", await asyncio.to_thread(svc.metrics.snapshot))
        await asyncio.sleep(svc.settings.metrics_interval_s)


def _voice_probe(voice: VoiceEngine) -> Any:
    async def probe() -> ProbeResult:
        caps = await asyncio.to_thread(voice.capabilities)
        if not caps.capture:
            return ProbeResult("degraded", caps.capture_detail or "microphone unavailable")
        n = len(await asyncio.to_thread(voice.devices))
        return ProbeResult("healthy", f"{n} input device{'s' if n != 1 else ''}")

    return probe


def create_app(settings: Settings, audio_backend: AudioBackend | None = None) -> FastAPI:
    register_secret(settings.session_token.get_secret_value())
    holder: dict[str, Services] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        db = Database(settings.resolved_database_url)
        await asyncio.to_thread(db.migrate)
        await asyncio.to_thread(_register_device, db)
        audit = AuditLog(db)
        health = HealthRegistry()
        health.register("api", api_probe)
        health.register("database", database_probe(db))
        health.register("disk", disk_probe(settings.data_dir))
        hub = Hub()
        hub.loop = asyncio.get_running_loop()
        store = SettingsStore(db)
        backend = audio_backend if audio_backend is not None else SoundDeviceBackend()
        voice = VoiceEngine(backend, store, audit, hub.publish_threadsafe)
        health.register("voice", _voice_probe(voice))
        svc = Services(settings, db, audit, TaskStore(db, audit), health, hub, time.monotonic(),
                       store, NotificationCentre(db, hub.publish_threadsafe), voice,
                       SystemMetrics(settings.data_dir))
        holder["svc"] = svc
        app.state.svc = svc
        await asyncio.to_thread(audit.record, "service.start", outcome="info",
                                details={"version": VERSION, "pid": os.getpid()})
        loop_task = asyncio.create_task(_health_loop(svc))
        metrics_task = asyncio.create_task(_metrics_loop(svc))
        log.info("JACK service ready on %s:%s (db=%s)", settings.host, settings.port, db.backend)
        try:
            yield
        finally:
            await asyncio.to_thread(voice.shutdown)
            for t in (loop_task, metrics_task):
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
            await asyncio.to_thread(audit.record, "service.stop", outcome="info")
            db.dispose()

    app = FastAPI(title="JACK AI Local Service", version=VERSION, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url="/v1/openapi.json")

    # Middleware order: last added runs first. Auth (incl. Host check) must be outermost.
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins),
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"], max_age=600)
    app.add_middleware(LoopbackAuthMiddleware, settings=settings,
                       audit_factory=lambda: holder["svc"].audit if "svc" in holder else None)

    def svc_of(request: Request) -> Services:
        s: Services = request.app.state.svc
        return s

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": {
            "code": "validation_error", "message": "Request validation failed",
            "request_id": None, "details": json.loads(json.dumps(exc.errors(), default=str))}})

    @app.exception_handler(VoiceBlocked)
    async def _voice_blocked(_: Request, exc: VoiceBlocked) -> JSONResponse:
        return _error(409, exc.code, str(exc))

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        code = {404: "not_found", 409: "invalid_transition"}.get(exc.status_code, "error")
        return _error(exc.status_code, code, str(exc.detail))

    # ---------------------------------------------------------------- health / system
    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/health", response_model=schemas.HealthReport)
    async def health(request: Request) -> dict[str, Any]:
        svc = svc_of(request)
        results, _ = await svc.health.check()
        return {"status": svc.health.overall(results), "version": VERSION,
                "uptime_s": round(time.monotonic() - svc.started_at, 1),
                "components": svc.health.as_dicts(results)}

    @app.get("/v1/system/info", response_model=schemas.SystemInfo)
    async def system_info(request: Request) -> dict[str, Any]:
        svc = svc_of(request)
        return {"app_version": VERSION, "python_version": sys.version.split()[0],
                "platform": platform.platform(), "data_dir": str(svc.settings.data_dir),
                "database_backend": svc.db.backend, "pid": os.getpid(),
                "ws_clients": svc.hub.count}

    # ---------------------------------------------------------------- tasks
    def _task_detail(svc: Services, task_id: str) -> schemas.TaskDetail:
        try:
            task, events = svc.tasks.get(task_id)
        except TaskNotFound as exc:
            raise HTTPException(404, "Task not found") from exc
        return schemas.TaskDetail(
            **schemas.TaskOut.model_validate(task).model_dump(),
            events=[schemas.TaskEventOut.model_validate(e) for e in events])

    def _publish(svc: Services, topic: str, task: Any) -> None:
        svc.hub.publish_threadsafe(topic, schemas.TaskOut.model_validate(task)
                                   .model_dump(mode="json"))

    @app.post("/v1/tasks", status_code=201, response_model=schemas.TaskOut)
    def create_task(body: schemas.TaskCreate, request: Request) -> Any:
        svc = svc_of(request)
        task = svc.tasks.create(body.command_text, body.source, body.title, LOCAL_USER)
        _publish(svc, "task.created", task)
        return task

    @app.get("/v1/tasks", response_model=schemas.TaskList)
    def list_tasks(request: Request, status: TaskStatus | None = None,
                   limit: Annotated[int, Query(ge=1, le=200)] = 50,
                   offset: Annotated[int, Query(ge=0)] = 0) -> Any:
        items, total = svc_of(request).tasks.list(status, limit, offset)
        return {"items": items, "total": total}

    @app.get("/v1/tasks/{task_id}", response_model=schemas.TaskDetail)
    def get_task(task_id: str, request: Request) -> Any:
        return _task_detail(svc_of(request), task_id)

    def _transition(request: Request, task_id: str, target: TaskStatus | None,
                    reason: str | None) -> Any:
        svc = svc_of(request)
        try:
            if target is None:
                task = svc.tasks.resume(task_id, reason, LOCAL_USER)
            else:
                task = svc.tasks.transition(task_id, target, reason, LOCAL_USER)
        except TaskNotFound as exc:
            raise HTTPException(404, "Task not found") from exc
        except InvalidTransition as exc:
            raise HTTPException(409, str(exc)) from exc
        _publish(svc, "task.updated", task)
        if task.status in NOTIFY_TASK_STATES:
            level, title = NOTIFY_TASK_STATES[task.status]
            svc.notifications.create(f"task.{task.status.lower()}", title, task.title,
                                     level=level, task_id=task.id)  # type: ignore[arg-type]
        return task

    @app.post("/v1/tasks/{task_id}/transition", response_model=schemas.TaskOut)
    def transition(task_id: str, body: schemas.TaskTransition, request: Request) -> Any:
        return _transition(request, task_id, body.to_status, body.reason)

    @app.post("/v1/tasks/{task_id}/pause", response_model=schemas.TaskOut)
    def pause(task_id: str, body: schemas.ReasonBody, request: Request) -> Any:
        return _transition(request, task_id, TaskStatus.PAUSED, body.reason)

    @app.post("/v1/tasks/{task_id}/resume", response_model=schemas.TaskOut)
    def resume(task_id: str, body: schemas.ReasonBody, request: Request) -> Any:
        return _transition(request, task_id, None, body.reason)

    @app.post("/v1/tasks/{task_id}/cancel", response_model=schemas.TaskOut)
    def cancel(task_id: str, body: schemas.ReasonBody, request: Request) -> Any:
        return _transition(request, task_id, TaskStatus.CANCELLED, body.reason)

    # ---------------------------------------------------------------- audit
    @app.get("/v1/audit", response_model=schemas.AuditList)
    def audit_list(request: Request, limit: Annotated[int, Query(ge=1, le=500)] = 100,
                   offset: Annotated[int, Query(ge=0)] = 0) -> Any:
        items, total = svc_of(request).audit.list(limit, offset)
        return {"items": items, "total": total}

    @app.get("/v1/audit/verify", response_model=schemas.AuditVerify)
    def audit_verify(request: Request) -> Any:
        r = svc_of(request).audit.verify()
        return {"valid": r.valid, "checked": r.checked, "first_invalid_seq": r.first_invalid_seq}

    app.include_router(m2_router)

    # ---------------------------------------------------------------- websocket
    @app.websocket("/v1/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        svc: Services = ws.app.state.svc
        await ws.accept()
        try:
            raw = await asyncio.wait_for(ws.receive_text(), svc.settings.ws_auth_timeout_s)
            msg = json.loads(raw)
            ok = (isinstance(msg, dict) and msg.get("type") == "auth"
                  and token_matches(str(msg.get("token", "")),
                                    svc.settings.session_token.get_secret_value()))
        except (TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
            ok = False
        if not ok:
            await asyncio.to_thread(svc.audit.record, "api.auth", outcome="denied",
                                    actor_type="unknown", target="/v1/ws",
                                    details={"reason": "ws_auth_failed"})
            with contextlib.suppress(Exception):
                await ws.close(code=4401)
            return

        try:
            # Send hello + snapshot before subscribing, so `hello` is always the first frame.
            await ws.send_text(envelope("hello", {"version": VERSION}))
            results, _ = await svc.health.check()
            await ws.send_text(envelope("health.changed", {
                "status": svc.health.overall(results),
                "components": svc.health.as_dicts(results)}))
            await svc.hub.add(ws)
            while True:
                raw = await ws.receive_text()
                with contextlib.suppress(json.JSONDecodeError):
                    if json.loads(raw).get("type") == "ping":
                        await ws.send_text(envelope("pong", {}))
        except WebSocketDisconnect:
            pass
        finally:
            await svc.hub.remove(ws)

    return app
