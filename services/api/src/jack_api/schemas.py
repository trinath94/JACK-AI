from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jack_api.tasks import TaskStatus


class ComponentHealthOut(BaseModel):
    name: str
    status: Literal["healthy", "degraded", "unhealthy"]
    detail: str | None
    latency_ms: float
    checked_at: str


class HealthReport(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    uptime_s: float
    components: list[ComponentHealthOut]


class SystemInfo(BaseModel):
    app_version: str
    python_version: str
    platform: str
    data_dir: str
    database_backend: str
    pid: int
    ws_clients: int


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_text: str = Field(min_length=1, max_length=4000)
    source: Literal["text", "voice"] = "text"
    title: str | None = Field(default=None, max_length=255)


class TaskTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_status: TaskStatus
    reason: str | None = Field(default=None, max_length=2000)


class ReasonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=2000)


class TaskEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    seq: int
    from_status: str | None
    to_status: str
    reason: str | None
    actor: str
    occurred_at: datetime


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    command_text: str
    source: str
    status: TaskStatus
    status_reason: str | None
    mode: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class TaskDetail(TaskOut):
    events: list[TaskEventOut]


class TaskList(BaseModel):
    items: list[TaskOut]
    total: int


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    seq: int
    occurred_at: datetime
    actor_type: str
    actor_id: str | None
    action: str
    target: str | None
    outcome: str
    details: dict[str, object]
    hash: str


class AuditList(BaseModel):
    items: list[AuditEventOut]
    total: int


class AuditVerify(BaseModel):
    valid: bool
    checked: int
    first_invalid_seq: int | None
