"""Milestone 2 routes: voice interface, notification centre, system metrics."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Annotated, Any, Literal

import anyio
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from jack_api.notifications import to_dict
from jack_api.voice.engine import VoiceSettings, VoiceSettingsPatch

if TYPE_CHECKING:
    from jack_api.app import Services

router = APIRouter(prefix="/v1")


def _svc(request: Request) -> Services:
    svc: Services = request.app.state.svc
    return svc


# ------------------------------------------------------------------------ schemas
class AudioDeviceOut(BaseModel):
    id: str
    name: str
    host_api: str
    is_default: bool
    channels: int


class VoiceCapabilities(BaseModel):
    capture: bool
    capture_detail: str | None
    wake_word: bool
    speech_recognition: bool
    speech_synthesis: bool
    pending_milestone: int


class VoiceStatus(BaseModel):
    state: Literal["disabled", "idle", "listening", "processing", "speaking"]
    settings: VoiceSettings
    capabilities: VoiceCapabilities
    listening_since_s: float | None


class PttStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["ui", "hotkey", "tray"] = "ui"


class PttResultOut(BaseModel):
    captured_ms: int
    transcribed: bool
    transcript: str | None
    detail: str
    stopped_by: str


class NotificationOut(BaseModel):
    id: str
    level: Literal["info", "success", "warning", "error"]
    kind: str
    title: str
    body: str | None
    task_id: str | None
    created_at: str
    read_at: str | None


class NotificationList(BaseModel):
    items: list[NotificationOut]
    total: int
    unread: int


class SystemMetricsOut(BaseModel):
    cpu_percent: float
    cpu_count: int
    memory_total_bytes: int
    memory_used_bytes: int
    memory_percent: float
    disk_total_bytes: int
    disk_free_bytes: int
    disk_percent: float
    service_rss_bytes: int
    service_cpu_percent: float
    uptime_s: int


# ------------------------------------------------------------------------ voice
@router.get("/voice/status", response_model=VoiceStatus)
def voice_status(request: Request) -> Any:
    return _svc(request).voice.snapshot()


@router.get("/voice/devices", response_model=list[AudioDeviceOut])
def voice_devices(request: Request) -> Any:
    return [asdict(d) for d in _svc(request).voice.devices()]


@router.patch("/voice/settings", response_model=VoiceSettings)
def voice_settings(body: VoiceSettingsPatch, request: Request) -> Any:
    return _svc(request).voice.update_settings(body)


@router.post("/voice/ptt/start", response_model=VoiceStatus)
def ptt_start(body: PttStart, request: Request) -> Any:
    voice = _svc(request).voice
    voice.start_ptt(body.source)
    return voice.snapshot()


@router.post("/voice/ptt/stop", response_model=PttResultOut | None)
def ptt_stop(request: Request) -> Any:
    result = _svc(request).voice.stop_ptt("released")
    return asdict(result) if result else None


# ------------------------------------------------------------------------ notifications
@router.get("/notifications", response_model=NotificationList)
def notifications(request: Request, unread_only: bool = False,
                  limit: Annotated[int, Query(ge=1, le=200)] = 50,
                  offset: Annotated[int, Query(ge=0)] = 0) -> Any:
    items, total, unread = _svc(request).notifications.list(unread_only, limit, offset)
    return {"items": [to_dict(n) for n in items], "total": total, "unread": unread}


@router.post("/notifications/{notification_id}/read", status_code=204)
def notification_read(notification_id: str, request: Request) -> None:
    if not _svc(request).notifications.mark_read(notification_id):
        raise HTTPException(404, "Notification not found")


@router.post("/notifications/read-all")
def notifications_read_all(request: Request) -> dict[str, int]:
    return {"marked": _svc(request).notifications.mark_all_read()}


# ------------------------------------------------------------------------ metrics
@router.get("/system/metrics", response_model=SystemMetricsOut)
async def system_metrics(request: Request) -> Any:
    return await anyio.to_thread.run_sync(_svc(request).metrics.snapshot)
