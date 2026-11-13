"""Requirement discovery routes (Milestone 5)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from jack_api.discovery.catalog import CATEGORIES
from jack_api.discovery.engine import (
    DiscoverySettingsPatch,
    Reply,
    SessionClosed,
    SessionNotFound,
    reply_dict,
)

if TYPE_CHECKING:
    from jack_api.app import Services
    from jack_api.discovery.engine import DiscoveryEngine

router = APIRouter()


def _eng(request: Request) -> DiscoveryEngine:
    svc: Services = request.app.state.svc
    return svc.discovery


class MessageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    source: Literal["typed", "ui"] = "typed"


class AnswerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)


class SlotValueBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str | bool | list[str]


def _guard[T](fn: Callable[[], T]) -> T:
    try:
        return fn()
    except SessionNotFound as exc:
        raise HTTPException(404, "Requirements conversation not found") from exc
    except SessionClosed as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _out(eng: DiscoveryEngine, r: Reply) -> dict[str, Any]:
    return {"reply": reply_dict(r), "session": eng.get(r.session_id)}


@router.get("/v1/discovery/status")
def status(request: Request) -> dict[str, Any]:
    return _eng(request).engine_status()


@router.patch("/v1/discovery/settings")
def update_settings(body: DiscoverySettingsPatch, request: Request) -> dict[str, Any]:
    return _eng(request).update_settings(body).model_dump()


@router.get("/v1/discovery/catalog")
def catalog() -> list[dict[str, Any]]:
    return [{"id": c.id, "name": c.name, "description": c.description,
             "questions": sum(1 for s in c.slots if s.essential)} for c in CATEGORIES]


@router.post("/v1/discovery/messages")
def message(body: MessageBody, request: Request) -> dict[str, Any]:
    eng = _eng(request)
    r = _guard(lambda: eng.message(body.text, source=body.source, session_id=body.session_id))
    return _out(eng, r)


@router.get("/v1/discovery/sessions")
def sessions(request: Request, active: bool = False) -> list[dict[str, Any]]:
    return _eng(request).sessions(active_only=active)


@router.get("/v1/discovery/sessions/{session_id}")
def session(session_id: str, request: Request) -> dict[str, Any]:
    return _guard(lambda: _eng(request).get(session_id))


@router.put("/v1/discovery/sessions/{session_id}/answers/{slot}")
def set_answer(session_id: str, slot: str, body: SlotValueBody,
               request: Request) -> dict[str, Any]:
    eng = _eng(request)
    r = _guard(lambda: eng.set_answer(session_id, slot, body.value))
    return _out(eng, r)


@router.post("/v1/discovery/sessions/{session_id}/approve")
def approve(session_id: str, request: Request) -> dict[str, Any]:
    eng = _eng(request)
    r = _guard(lambda: eng.approve(session_id))
    return _out(eng, r)


@router.post("/v1/discovery/sessions/{session_id}/cancel")
def cancel(session_id: str, request: Request) -> dict[str, Any]:
    eng = _eng(request)
    r = _guard(lambda: eng.cancel(session_id))
    return _out(eng, r)


# Task-scoped routes drafted in API_CONTRACTS.md before M5.
@router.post("/v1/tasks/{task_id}/answers")
def task_answer(task_id: str, body: AnswerBody, request: Request) -> dict[str, Any]:
    eng = _eng(request)
    r = _guard(lambda: eng.answer_task(task_id, body.text, "typed"))
    return _out(eng, r)


@router.get("/v1/tasks/{task_id}/spec")
def task_spec(task_id: str, request: Request) -> dict[str, Any]:
    view = _guard(lambda: _eng(request).for_task(task_id))
    if view["spec"] is None:
        raise HTTPException(404, "No specification yet: requirements are still being gathered")
    return {"spec": view["spec"], "status": view["status"], "session_id": view["id"]}


@router.post("/v1/tasks/{task_id}/spec/approve")
def task_spec_approve(task_id: str, request: Request) -> dict[str, Any]:
    eng = _eng(request)
    view = _guard(lambda: eng.for_task(task_id))
    r = _guard(lambda: eng.approve(view["id"]))
    return _out(eng, r)
