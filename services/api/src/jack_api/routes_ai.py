"""AI provider routes (Milestone 4): credentials, settings, checks, test console, usage."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

import anyio
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from jack_api.ai.credentials import CredentialStoreUnavailable
from jack_api.ai.providers import ProviderError
from jack_api.ai.service import AISettings, AISettingsPatch, month_key

if TYPE_CHECKING:
    from jack_api.app import Services

router = APIRouter(prefix="/v1/ai")


def _svc(request: Request) -> Services:
    svc: Services = request.app.state.svc
    return svc


class ApiKeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str = Field(min_length=10, max_length=300)


class CompleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=20000)
    provider: Literal["anthropic", "claude_code"] | None = None
    system: str | None = Field(default=None, max_length=10000)
    max_tokens: int = Field(default=2048, ge=16, le=32000)
    task_id: str | None = None


def _provider_error(exc: ProviderError) -> HTTPException:
    status = {"not_configured": 409, "budget": 402, "auth": 401, "permission": 403,
              "not_found": 404, "bad_request": 400, "rate_limited": 429, "unavailable": 409,
              "timeout": 504}.get(exc.code, 502)
    return HTTPException(status, detail={"code": f"ai_{exc.code}", "message": str(exc)})


@router.get("/status")
def status(request: Request) -> Any:
    return _svc(request).ai.status()


@router.put("/anthropic/key", status_code=204)
def set_key(body: ApiKeyBody, request: Request) -> None:
    try:
        _svc(request).ai.set_anthropic_key(body.api_key)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "invalid_api_key", "message": str(exc)}) from exc
    except CredentialStoreUnavailable as exc:
        raise HTTPException(409, detail={"code": "credential_store_unavailable",
                                         "message": str(exc)}) from exc


@router.delete("/anthropic/key", status_code=204)
def delete_key(request: Request) -> None:
    _svc(request).ai.delete_anthropic_key()


@router.patch("/settings", response_model=AISettings)
def update_settings(body: AISettingsPatch, request: Request) -> Any:
    try:
        return _svc(request).ai.update_settings(body)
    except ValueError as exc:  # pydantic ValidationError is a ValueError
        raise HTTPException(422, detail={"code": "validation_error",
                                         "message": str(exc)[:500]}) from exc


@router.get("/anthropic/models")
async def models(request: Request, refresh: bool = False) -> Any:
    try:
        return await anyio.to_thread.run_sync(lambda: _svc(request).ai.models(refresh))
    except ProviderError as exc:
        raise _provider_error(exc) from exc


@router.post("/{provider}/test")
async def test(provider: Literal["anthropic", "claude_code"], request: Request) -> Any:
    return await anyio.to_thread.run_sync(lambda: _svc(request).ai.test(provider))


@router.post("/claude-code/detect")
async def detect(request: Request) -> Any:
    return await anyio.to_thread.run_sync(_svc(request).ai.detect_claude_code)


@router.post("/complete")
async def complete(body: CompleteBody, request: Request) -> Any:
    svc = _svc(request)
    try:
        return await anyio.to_thread.run_sync(lambda: svc.ai.complete(
            body.prompt, purpose="console", provider=body.provider, system=body.system,
            max_tokens=body.max_tokens, task_id=body.task_id))
    except ProviderError as exc:
        raise _provider_error(exc) from exc


@router.get("/usage")
def usage(request: Request, month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None
          ) -> Any:
    return _svc(request).ai.month_summary(month or month_key())


@router.get("/usage/records")
def usage_records(request: Request, limit: Annotated[int, Query(ge=1, le=500)] = 100,
                  offset: Annotated[int, Query(ge=0)] = 0) -> Any:
    items, total = _svc(request).ai.records(limit, offset)
    return {"items": items, "total": total}
