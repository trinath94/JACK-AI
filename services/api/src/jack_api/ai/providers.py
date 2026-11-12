"""AI providers behind one interface (Section 5).

* ``AnthropicApiProvider`` — the Anthropic API via the official SDK, with an API key the user
  stores in JACK (Windows Credential Manager). JACK always passes that key explicitly, so the
  SDK never silently picks up other credentials from the environment.
* ``ClaudeCodeProvider`` — the user's installed Claude Code CLI, using **Claude Code's own**
  supported sign-in (API key or the user's Claude plan). JACK never reads, copies or extracts
  those credentials; it only runs ``claude`` and reads ``claude auth status``.

Claude Pro/Max subscriptions are not API credits: Claude Code usage is recorded with its own
billing kind and never mixed into API cost totals.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Protocol

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
ANTHROPIC_BASE_URL = "https://api.anthropic.com"
# Models on which the API's server-side refusal fallback is available.
SERVER_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5",
                          "claude-fable-5-1", "claude-fable-5-2"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
NO_EFFORT_MODELS = {"claude-haiku-4-5"}

BillingKind = Literal["api", "claude_code"]
ErrorCode = Literal["not_configured", "auth", "permission", "not_found", "bad_request",
                    "rate_limited", "overloaded", "server", "timeout", "network", "refused",
                    "budget", "cli_error", "unavailable"]


@dataclass
class UsagePart:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0


@dataclass
class Completion:
    text: str
    model_requested: str
    model_served: str
    stop_reason: str | None
    usage: list[UsagePart]
    billing_kind: BillingKind
    latency_ms: int
    request_id: str | None = None
    refusal_category: str | None = None
    fallbacks: list[tuple[str, str]] = field(default_factory=list)  # (from, to) models
    reported_cost_usd: Decimal | None = None  # Claude Code reports its own estimate
    auth_method: str | None = None


class ProviderError(Exception):
    def __init__(self, code: ErrorCode, message: str, *, retryable: bool = False,
                 request_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.request_id = request_id


@dataclass
class Request:
    prompt: str
    system: str | None = None
    model: str | None = None
    max_tokens: int = 4096
    effort: str | None = None
    max_budget_usd: float | None = None


class Provider(Protocol):
    id: str
    kind: str
    billing_kind: BillingKind

    def complete(self, req: Request) -> Completion: ...


# =============================================================================== Anthropic
@dataclass
class AnthropicConfig:
    model: str = DEFAULT_MODEL
    effort: str | None = "medium"
    timeout_s: float = 120.0
    max_retries: int = 2
    refusal_fallback: bool = True
    base_url: str = ANTHROPIC_BASE_URL


class AnthropicApiProvider:
    id = "anthropic"
    kind = "anthropic_api"
    billing_kind: BillingKind = "api"

    def __init__(self, get_key: Callable[[], str | None],
                 get_config: Callable[[], AnthropicConfig]) -> None:
        self._get_key = get_key
        self._get_config = get_config

    def _client(self, cfg: AnthropicConfig) -> Any:
        key = self._get_key()
        if not key:
            raise ProviderError("not_configured", "No Anthropic API key is stored in JACK")
        import anthropic

        return anthropic.Anthropic(api_key=key, base_url=cfg.base_url, timeout=cfg.timeout_s,
                                   max_retries=cfg.max_retries)

    def configured(self) -> bool:
        return bool(self._get_key())

    def complete(self, req: Request) -> Completion:
        cfg = self._get_config()
        client = self._client(cfg)
        model = req.model or cfg.model
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": req.max_tokens,
            "messages": [{"role": "user", "content": req.prompt}],
        }
        if req.system:
            kwargs["system"] = req.system
        effort = req.effort or cfg.effort
        if effort and model not in NO_EFFORT_MODELS:
            kwargs["output_config"] = {"effort": effort}
        start = time.monotonic()
        try:
            if cfg.refusal_fallback and model in SERVER_FALLBACK_MODELS:
                msg = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default",
                                                  **kwargs)
            else:
                msg = client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - mapped to typed provider errors below
            raise _map_anthropic_error(exc) from exc
        latency = int((time.monotonic() - start) * 1000)
        return _parse_message(msg, model, latency)

    def models(self) -> list[dict[str, Any]]:
        cfg = self._get_config()
        client = self._client(cfg)
        try:
            page = client.models.list(limit=100)
            items = list(page)
        except Exception as exc:  # noqa: BLE001
            raise _map_anthropic_error(exc) from exc
        return [{"id": m.id, "display_name": m.display_name,
                 "max_input_tokens": getattr(m, "max_input_tokens", None),
                 "max_tokens": getattr(m, "max_tokens", None)} for m in items]


def _parse_message(msg: Any, requested: str, latency_ms: int) -> Completion:
    texts: list[str] = []
    fallbacks: list[tuple[str, str]] = []
    for block in msg.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            texts.append(block.text)
        elif btype == "fallback":
            fallbacks.append((getattr(block.from_, "model", "?"),
                              getattr(block.to, "model", "?")))
    usage = msg.usage
    parts: list[UsagePart] = []
    iterations = getattr(usage, "iterations", None) or []
    for it in iterations:
        if getattr(it, "type", "") in ("message", "fallback_message", "advisor_message",
                                        "compaction"):
            parts.append(_usage_part(it, getattr(it, "model", None) or msg.model))
    if not parts:
        parts.append(_usage_part(usage, msg.model))
    refusal = None
    if msg.stop_reason == "refusal" and getattr(msg, "stop_details", None) is not None:
        refusal = getattr(msg.stop_details, "category", None) or "unspecified"
    return Completion(text="".join(texts).strip(), model_requested=requested,
                      model_served=msg.model, stop_reason=msg.stop_reason, usage=parts,
                      billing_kind="api", latency_ms=latency_ms,
                      request_id=getattr(msg, "_request_id", None), refusal_category=refusal,
                      fallbacks=fallbacks)


def _usage_part(u: Any, model: str) -> UsagePart:
    cc = getattr(u, "cache_creation", None)
    w5 = getattr(cc, "ephemeral_5m_input_tokens", None) if cc is not None else None
    w1 = getattr(cc, "ephemeral_1h_input_tokens", None) if cc is not None else None
    if w5 is None and w1 is None:
        w5, w1 = getattr(u, "cache_creation_input_tokens", 0) or 0, 0
    return UsagePart(model=model, input_tokens=getattr(u, "input_tokens", 0) or 0,
                     output_tokens=getattr(u, "output_tokens", 0) or 0,
                     cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
                     cache_write_5m=w5 or 0, cache_write_1h=w1 or 0)


def _map_anthropic_error(exc: Exception) -> ProviderError:
    import anthropic

    rid = getattr(exc, "request_id", None)
    if isinstance(exc, anthropic.AuthenticationError):
        return ProviderError("auth", "The Anthropic API key was rejected", request_id=rid)
    if isinstance(exc, anthropic.PermissionDeniedError):
        return ProviderError("permission", "The API key is not allowed to do this",
                             request_id=rid)
    if isinstance(exc, anthropic.NotFoundError):
        return ProviderError("not_found", "Model or endpoint not found", request_id=rid)
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderError("rate_limited", "Rate limited by the Anthropic API", retryable=True,
                             request_id=rid)
    if isinstance(exc, anthropic.BadRequestError):
        return ProviderError("bad_request", f"Request rejected: {_msg(exc)}", request_id=rid)
    if isinstance(exc, anthropic.APITimeoutError):
        return ProviderError("timeout", "The Anthropic API did not answer in time",
                             retryable=True)
    if isinstance(exc, anthropic.APIStatusError):
        code: ErrorCode = "overloaded" if exc.status_code == 529 else "server"
        return ProviderError(code, f"Anthropic API error {exc.status_code}", retryable=True,
                             request_id=rid)
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderError("network", "Could not reach the Anthropic API", retryable=True)
    return ProviderError("server", f"Unexpected error: {type(exc).__name__}")


def _msg(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return str(err["message"])[:300]
    return str(getattr(exc, "message", exc))[:300]


# =============================================================================== Claude Code
@dataclass
class ClaudeCodeConfig:
    binary: str | None = None
    model: str | None = None
    timeout_s: float = 300.0


# Never hand JACK's own secrets to a child process.
_SCRUB_ENV = ("JACK_SESSION_TOKEN", "JACK_INSECURE_TEST_CREDENTIALS")


def find_claude(configured: str | None) -> str | None:
    if configured:
        return configured if Path(configured).exists() else None
    found = shutil.which("claude")
    if found:
        return found
    if sys.platform == "win32":
        for base in (os.environ.get("APPDATA"), os.environ.get("USERPROFILE")):
            if not base:
                continue
            for rel in (r"npm\claude.cmd", r".local\bin\claude.exe"):
                p = Path(base) / rel
                if p.exists():
                    return str(p)
    return None


class ClaudeCodeProvider:
    id = "claude_code"
    kind = "claude_code"
    billing_kind: BillingKind = "claude_code"

    def __init__(self, get_config: Callable[[], ClaudeCodeConfig]) -> None:
        self._get_config = get_config

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        for k in _SCRUB_ENV:
            env.pop(k, None)
        return env

    def _run(self, args: list[str], *, stdin: str | None = None, timeout: float = 30.0,
             cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        binary = find_claude(self._get_config().binary)
        if binary is None:
            raise ProviderError("unavailable", "Claude Code is not installed (claude not found)")
        try:
            return subprocess.run([binary, *args], input=stdin, capture_output=True,  # noqa: S603
                                  text=True, timeout=timeout, env=self._env(), cwd=cwd,
                                  check=False)
        except subprocess.TimeoutExpired as exc:
            raise ProviderError("timeout", "Claude Code did not finish in time",
                                retryable=True) from exc
        except OSError as exc:
            raise ProviderError("unavailable", f"Could not start Claude Code: {exc}") from exc

    def detect(self) -> dict[str, Any]:
        binary = find_claude(self._get_config().binary)
        if binary is None:
            return {"installed": False, "binary": None, "version": None, "logged_in": False,
                    "auth_method": None, "api_provider": None,
                    "detail": "Claude Code is not installed"}
        version = self._run(["--version"], timeout=20).stdout.strip() or None
        status = self._run(["auth", "status", "--json"], timeout=20)
        info: dict[str, Any] = {}
        try:
            info = json.loads(status.stdout or "{}")
        except json.JSONDecodeError:
            info = {}
        logged_in = bool(info.get("loggedIn"))
        return {"installed": True, "binary": binary, "version": version, "logged_in": logged_in,
                "auth_method": info.get("authMethod"), "api_provider": info.get("apiProvider"),
                "detail": None if logged_in else
                "Claude Code is not signed in. Run `claude` once and sign in."}

    def complete(self, req: Request) -> Completion:
        cfg = self._get_config()
        model = req.model or cfg.model
        args = ["-p", "--output-format", "json", "--max-turns", "1",
                "--no-session-persistence", "--permission-mode", "default"]
        if model:
            args += ["--model", model]
        if req.max_budget_usd is not None:
            args += ["--max-budget-usd", f"{req.max_budget_usd:.4f}"]
        if req.system:
            args += ["--append-system-prompt", req.system]
        start = time.monotonic()
        # An empty working directory: a plain completion must not read the user's files.
        with tempfile.TemporaryDirectory(prefix="jack-cc-") as cwd:
            proc = self._run(args, stdin=req.prompt, timeout=cfg.timeout_s, cwd=cwd)
        latency = int((time.monotonic() - start) * 1000)
        try:
            data = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
        except (json.JSONDecodeError, IndexError):
            data = {}
        if proc.returncode != 0 and not data:
            err = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["unknown error"]
            raise ProviderError("cli_error", f"Claude Code failed: {err[0][:300]}")
        if data.get("is_error"):
            raise ProviderError("cli_error", f"Claude Code reported an error: "
                                f"{str(data.get('result') or data.get('subtype'))[:300]}")
        usage = data.get("usage") or {}
        parts: list[UsagePart] = []
        for m, u in (data.get("modelUsage") or {}).items():
            parts.append(UsagePart(model=m, input_tokens=int(u.get("inputTokens", 0)),
                                   output_tokens=int(u.get("outputTokens", 0)),
                                   cache_read=int(u.get("cacheReadInputTokens", 0)),
                                   cache_write_5m=int(u.get("cacheCreationInputTokens", 0))))
        if not parts:
            parts.append(UsagePart(model=model or "claude-code",
                                   input_tokens=int(usage.get("input_tokens", 0)),
                                   output_tokens=int(usage.get("output_tokens", 0)),
                                   cache_read=int(usage.get("cache_read_input_tokens", 0)),
                                   cache_write_5m=int(usage.get("cache_creation_input_tokens", 0))))
        cost = data.get("total_cost_usd")
        served = parts[0].model if parts else (model or "claude-code")
        return Completion(text=str(data.get("result") or "").strip(),
                          model_requested=model or "claude-code default", model_served=served,
                          stop_reason=str(data.get("subtype") or "success"), usage=parts,
                          billing_kind="claude_code", latency_ms=latency,
                          reported_cost_usd=Decimal(str(cost)) if cost is not None else None)
