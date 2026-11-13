"""Task execution, approvals and orchestrator routes (Milestone 6)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from jack_api.db import TaskArtifact, TaskStep, WorkflowRun
from jack_api.orchestrator.approvals import ApprovalError, approval_dict
from jack_api.orchestrator.service import OrchestratorUnavailable, orchestrator_status
from jack_api.tasks import TaskNotFound

if TYPE_CHECKING:
    from jack_api.app import Services

router = APIRouter()


def _svc(request: Request) -> Services:
    svc: Services = request.app.state.svc
    return svc


class DecideBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "deny"]
    nonce: str = Field(min_length=8, max_length=128)


def _step(st: TaskStep) -> dict[str, Any]:
    return {"id": st.id, "seq": st.seq, "key": st.key, "title": st.title, "kind": st.kind,
            "agent_role": st.agent_role, "idempotent": st.idempotent,
            "needs_approval": st.needs_approval, "status": st.status, "attempts": st.attempts,
            "blocked_reason": st.blocked_reason, "error": st.error,
            "output": {k: v for k, v in (st.output or {}).items() if k != "excerpt"} or None,
            "approval_id": st.approval_id, "started_at": st.started_at,
            "finished_at": st.finished_at}


@router.get("/v1/orchestrator/status")
def status(request: Request) -> dict[str, Any]:
    svc = _svc(request)
    o = svc.orchestrator
    state, detail = orchestrator_status(o)
    return {"status": state, "detail": detail, "recovered": o.recovered if o else {}}


@router.get("/v1/tasks/{task_id}/execution")
def execution(task_id: str, request: Request) -> dict[str, Any]:
    svc = _svc(request)
    try:
        task, _ = svc.tasks.get(task_id)
    except TaskNotFound as exc:
        raise HTTPException(404, "Task not found") from exc
    with svc.db.session() as s:
        steps = [_step(x) for x in s.scalars(select(TaskStep).where(TaskStep.task_id == task_id)
                                             .order_by(TaskStep.seq))]
        arts = [{"id": a.id, "name": a.name, "kind": a.kind, "size_bytes": a.size_bytes,
                 "sha256": a.sha256, "step_id": a.step_id, "path": a.path,
                 "created_at": a.created_at}
                for a in s.scalars(select(TaskArtifact).where(TaskArtifact.task_id == task_id)
                                   .order_by(TaskArtifact.created_at))]
        runs = [{"workflow_id": r.workflow_id, "run_id": r.run_id, "status": r.status,
                 "started_at": r.started_at, "ended_at": r.ended_at}
                for r in s.scalars(select(WorkflowRun).where(WorkflowRun.task_id == task_id)
                                   .order_by(WorkflowRun.started_at))]
    approvals = [approval_dict(a) for a in svc.approvals.list(task_id=task_id)]
    return {"task_id": task_id, "summary": task.summary, "steps": steps, "artifacts": arts,
            "approvals": approvals, "runs": runs}


@router.get("/v1/tasks/{task_id}/artifacts/{artifact_id}", response_class=PlainTextResponse)
def artifact(task_id: str, artifact_id: str, request: Request) -> str:
    svc = _svc(request)
    with svc.db.session() as s:
        a = s.get(TaskArtifact, artifact_id)
    if a is None or a.task_id != task_id:
        raise HTTPException(404, "Artifact not found")
    root = (svc.settings.data_dir / "workspaces").resolve()
    p = Path(a.path).resolve()
    if root not in p.parents or not p.is_file():  # only files JACK wrote in its workspaces
        raise HTTPException(404, "Artifact file is missing")
    return p.read_text(encoding="utf-8", errors="replace")[:2_000_000]


@router.post("/v1/tasks/{task_id}/retry")
def retry(task_id: str, request: Request) -> dict[str, Any]:
    svc = _svc(request)
    if svc.orchestrator is None:
        raise HTTPException(409, "Task orchestration is off")
    try:
        svc.orchestrator.retry(task_id)
    except TaskNotFound as exc:
        raise HTTPException(404, "Task not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except OrchestratorUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"retrying": True}


@router.get("/v1/approvals")
def approvals(request: Request, status: str | None = Query(default="pending"),
              limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    return [approval_dict(a) for a in _svc(request).approvals.list(status=status or None,
                                                                   limit=limit)]


@router.post("/v1/approvals/{approval_id}/decide")
def decide(approval_id: str, body: DecideBody, request: Request) -> dict[str, Any]:
    svc = _svc(request)
    try:
        a = svc.approvals.decide(approval_id, body.decision, body.nonce, via="ui")
    except ApprovalError as exc:
        code = {"not_found": 404, "not_pending": 409, "stale": 409}.get(exc.code, 400)
        raise HTTPException(code, {"code": f"approval_{exc.code}", "message": str(exc)}) \
            from exc
    return approval_dict(a)
