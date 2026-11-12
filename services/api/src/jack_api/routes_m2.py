"""Milestone 2 routes: notification centre and system metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

import anyio
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from jack_api.notifications import to_dict

if TYPE_CHECKING:
    from jack_api.app import Services

router = APIRouter(prefix="/v1")


def _svc(request: Request) -> Services:
    svc: Services = request.app.state.svc
    return svc


# ------------------------------------------------------------------------ schemas
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
