"""AI service: provider settings, routing, explicit fallback, spending limits, usage.

Rules (Sections 5, 20, 24):
* Credentials live in the credential store only; settings hold no secrets.
* Spending limits are checked before every call. A single call can exceed the remaining
  budget by at most its own cost; the next call is then refused.
* Falling back to a different provider changes cost and data handling, so it happens only if
  the user turned fallback on, and every fallback is audited and announced.
* Claude Code usage (which may be covered by the user's Claude plan) is never added to API
  spend; it is reported separately.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from jack_api.ai.credentials import CredentialStore, CredentialStoreUnavailable, hint
from jack_api.ai.pricing import PRICES, PRICES_AS_OF, estimate
from jack_api.ai.providers import (
    DEFAULT_MODEL,
    AnthropicApiProvider,
    AnthropicConfig,
    ClaudeCodeConfig,
    ClaudeCodeProvider,
    Completion,
    ProviderError,
    Request,
)
from jack_api.audit import AuditLog
from jack_api.db import Database, UsageRecord, utcnow
from jack_api.notifications import NotificationCentre
from jack_api.settings_store import SettingsStore

SETTINGS_KEY = "ai"
ALERTS_KEY = "ai.alerts_sent"
ANTHROPIC_KEY = "anthropic:api_key"
ProviderId = Literal["anthropic", "claude_code"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
Publisher = Callable[[str, Any], None]


class AnthropicSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(default=DEFAULT_MODEL, min_length=3, max_length=64)
    effort: Effort | None = "medium"
    timeout_s: float = Field(default=120, ge=10, le=600)
    max_retries: int = Field(default=2, ge=0, le=5)
    refusal_fallback: bool = True


class ClaudeCodeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    binary: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=64)
    timeout_s: float = Field(default=300, ge=30, le=1800)


class RoutingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reasoning: ProviderId = "anthropic"
    coding: ProviderId = "claude_code"


class FallbackSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False  # explicit opt-in: switching provider changes cost/data handling


class LimitSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    monthly_usd: Decimal | None = Field(default=None, ge=0, le=100000)
    per_task_usd: Decimal | None = Field(default=None, ge=0, le=100000)
    per_project_usd: Decimal | None = Field(default=None, ge=0, le=100000)
    alert_pct: list[int] = Field(default_factory=lambda: [50, 80, 100])


class AISettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anthropic: AnthropicSettings = Field(default_factory=AnthropicSettings)
    claude_code: ClaudeCodeSettings = Field(default_factory=ClaudeCodeSettings)
    routing: RoutingSettings = Field(default_factory=RoutingSettings)
    fallback: FallbackSettings = Field(default_factory=FallbackSettings)
    limits: LimitSettings = Field(default_factory=LimitSettings)


class AISettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anthropic: dict[str, Any] | None = None
    claude_code: dict[str, Any] | None = None
    routing: dict[str, Any] | None = None
    fallback: dict[str, Any] | None = None
    limits: dict[str, Any] | None = None


def month_key(dt: datetime | None = None) -> str:
    return (dt or datetime.now(UTC)).strftime("%Y-%m")


def month_start(key: str) -> datetime:
    y, m = (int(x) for x in key.split("-"))
    return datetime(y, m, 1, tzinfo=UTC)


def next_month(key: str) -> datetime:
    y, m = (int(x) for x in key.split("-"))
    return datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=UTC)


class AIService:
    def __init__(self, db: Database, store: SettingsStore, creds: CredentialStore,
                 audit: AuditLog, notifications: NotificationCentre, publish: Publisher,
                 anthropic_base_url: str | None = None) -> None:
        self._db = db
        self._store = store
        self._creds = creds
        self._audit = audit
        self._notes = notifications
        self._publish = publish
        self._lock = threading.Lock()
        self._settings = store.get(SETTINGS_KEY, AISettings)
        self._base_url = anthropic_base_url
        self._last_test: dict[str, dict[str, Any]] = {}
        self._models_cache: list[dict[str, Any]] | None = None
        self._cc_detect: dict[str, Any] | None = None
        self.anthropic = AnthropicApiProvider(self._anthropic_key, self._anthropic_config)
        self.claude_code = ClaudeCodeProvider(self._cc_config)

    # ------------------------------------------------------------------ config plumbing
    @property
    def settings(self) -> AISettings:
        return self._settings

    def _anthropic_key(self) -> str | None:
        try:
            return self._creds.get(ANTHROPIC_KEY)
        except Exception:  # noqa: BLE001 - an unreadable store reads as "not configured"
            return None

    def _anthropic_config(self) -> AnthropicConfig:
        a = self._settings.anthropic
        cfg = AnthropicConfig(model=a.model, effort=a.effort, timeout_s=a.timeout_s,
                              max_retries=a.max_retries, refusal_fallback=a.refusal_fallback)
        if self._base_url:
            cfg.base_url = self._base_url
        return cfg

    def _cc_config(self) -> ClaudeCodeConfig:
        c = self._settings.claude_code
        return ClaudeCodeConfig(binary=c.binary, model=c.model, timeout_s=c.timeout_s)

    # ------------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        key = self._anthropic_key()
        store_ok, store_detail = self._creds.available()
        s = self._settings
        return {
            "credential_store": {"kind": self._creds.kind, "secure": self._creds.secure,
                                 "available": store_ok, "detail": store_detail},
            "anthropic": {
                "configured": bool(key), "key_hint": hint(key),
                "settings": s.anthropic.model_dump(mode="json"),
                "last_test": self._last_test.get("anthropic"),
                "price_known": s.anthropic.model in PRICES,
            },
            "claude_code": {
                "settings": s.claude_code.model_dump(mode="json"),
                "detected": self._cc_detect,
                "last_test": self._last_test.get("claude_code"),
            },
            "routing": s.routing.model_dump(mode="json"),
            "fallback": s.fallback.model_dump(mode="json"),
            "limits": s.limits.model_dump(mode="json"),
            "prices_as_of": PRICES_AS_OF,
            "month": self.month_summary(month_key()),
        }

    # ------------------------------------------------------------------ settings & secrets
    def set_anthropic_key(self, key: str) -> None:
        key = key.strip()
        if not key.startswith("sk-ant-") or len(key) < 24 or any(c.isspace() for c in key):
            raise ValueError("That doesn't look like an Anthropic API key (sk-ant-…)")
        try:
            self._creds.set(ANTHROPIC_KEY, key)
        except CredentialStoreUnavailable:
            raise
        self._models_cache = None
        self._last_test.pop("anthropic", None)
        self._audit.record("credential.set", outcome="allowed", actor_type="user",
                           target="anthropic:api_key", details={"store": self._creds.kind,
                                                                 "hint": hint(key)})
        self._publish("ai.status", {"changed": "anthropic.key"})

    def delete_anthropic_key(self) -> None:
        self._creds.delete(ANTHROPIC_KEY)
        self._models_cache = None
        self._last_test.pop("anthropic", None)
        self._audit.record("credential.delete", outcome="allowed", actor_type="user",
                           target="anthropic:api_key")
        self._publish("ai.status", {"changed": "anthropic.key"})

    def update_settings(self, patch: AISettingsPatch) -> AISettings:
        with self._lock:
            data = self._settings.model_dump(mode="json")
            for section, changes in patch.model_dump(exclude_none=True).items():
                data[section] = {**data[section], **changes}
            new = AISettings.model_validate(data)
            self._store.put(SETTINGS_KEY, new)
            self._settings = new
        self._audit.record("ai.settings.update", outcome="allowed", actor_type="user",
                           details=patch.model_dump(exclude_none=True, mode="json"))
        self._publish("ai.status", {"changed": "settings"})
        return new

    # ------------------------------------------------------------------ provider checks
    def models(self, refresh: bool = False) -> list[dict[str, Any]]:
        if self._models_cache is None or refresh:
            models = self.anthropic.models()
            for m in models:
                m["price_known"] = m["id"] in PRICES
            self._models_cache = models
        return self._models_cache

    def detect_claude_code(self) -> dict[str, Any]:
        self._cc_detect = self.claude_code.detect()
        return self._cc_detect

    def test(self, provider: ProviderId) -> dict[str, Any]:
        at = utcnow().isoformat()
        try:
            out = self.complete("Reply with exactly the word OK.", purpose="connection_test",
                                provider=provider, max_tokens=512, effort="low",
                                allow_fallback=False)
            result = {"ok": True, "at": at, "model": out["model_served"],
                      "latency_ms": out["latency_ms"], "reply": out["text"][:80],
                      "error": None, "error_code": None}
        except ProviderError as exc:
            result = {"ok": False, "at": at, "model": None, "latency_ms": None, "reply": None,
                      "error": str(exc), "error_code": exc.code}
        self._last_test[provider] = result
        self._publish("ai.status", {"changed": f"{provider}.test"})
        return result

    # ------------------------------------------------------------------ completion
    def complete(self, prompt: str, *, purpose: str, provider: ProviderId | None = None,
                 route: Literal["reasoning", "coding"] = "reasoning",
                 task_id: str | None = None, project_id: str | None = None,
                 system: str | None = None, max_tokens: int = 4096,
                 effort: str | None = None, allow_fallback: bool = True) -> dict[str, Any]:
        primary: ProviderId = provider or getattr(self._settings.routing, route)
        self._check_limits(task_id, project_id, primary)
        req = Request(prompt=prompt, system=system, max_tokens=max_tokens, effort=effort,
                      max_budget_usd=self._remaining_task_budget(task_id))
        try:
            completion = self._call(primary, req)
            used = primary
        except ProviderError as exc:
            self._record_failure(primary, purpose, task_id, project_id, exc)
            other: ProviderId = "claude_code" if primary == "anthropic" else "anthropic"
            if not (allow_fallback and self._settings.fallback.enabled and exc.code in
                    ("not_configured", "rate_limited", "overloaded", "server", "timeout",
                     "network", "unavailable", "cli_error")):
                raise
            self._audit.record("ai.fallback", outcome="info", actor_type="system",
                               details={"from": primary, "to": other, "reason": exc.code,
                                        "purpose": purpose})
            self._notes.create("ai.fallback", f"Used {_name(other)} instead of {_name(primary)}",
                               f"{_name(primary)} failed ({exc.code}). Fallback is on in "
                               "Usage and Billing; costs and data handling may differ.",
                               level="warning", task_id=task_id)
            try:
                completion = self._call(other, req)
            except ProviderError as exc2:
                self._record_failure(other, purpose, task_id, project_id, exc2)
                raise
            used = other
        cost = self._record_success(used, completion, purpose, task_id, project_id)
        self._check_alerts()
        if completion.refusal_category:
            self._audit.record("ai.refusal", outcome="info", actor_type="system",
                               details={"category": completion.refusal_category,
                                        "model": completion.model_served})
        if completion.fallbacks:
            self._audit.record("ai.model_fallback", outcome="info", actor_type="system",
                               details={"fallbacks": [f"{a}->{b}" for a, b in
                                                      completion.fallbacks]})
        out = asdict(completion)
        out["usage"] = [asdict(u) for u in completion.usage]
        out["provider"] = used
        out["cost_usd"] = str(cost) if cost is not None else None
        out["reported_cost_usd"] = (str(completion.reported_cost_usd)
                                    if completion.reported_cost_usd is not None else None)
        return out

    def _call(self, pid: ProviderId, req: Request) -> Completion:
        if pid == "claude_code":
            if not self._settings.claude_code.enabled:
                raise ProviderError("not_configured", "Claude Code is turned off in JACK")
            return self.claude_code.complete(req)
        return self.anthropic.complete(req)

    # ------------------------------------------------------------------ usage recording
    def _record_success(self, pid: str, c: Completion, purpose: str, task_id: str | None,
                        project_id: str | None) -> Decimal | None:
        total: Decimal | None = Decimal(0)
        rows = []
        for i, u in enumerate(c.usage):
            if c.billing_kind == "api":
                cost = estimate(u.model, u.input_tokens, u.output_tokens, u.cache_read,
                                u.cache_write_5m, u.cache_write_1h)
                source = "estimated" if cost is not None else "unknown"
            else:
                cost = c.reported_cost_usd if i == 0 else None
                source = "reported" if cost is not None else "none"
            if cost is None and c.billing_kind == "api":
                total = None
            elif total is not None and cost is not None:
                total += cost
            rows.append(UsageRecord(
                provider_id=pid, billing_kind=c.billing_kind, model_requested=c.model_requested,
                model=u.model, purpose=purpose, task_id=task_id, project_id=project_id,
                input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                cache_read_tokens=u.cache_read,
                cache_write_tokens=u.cache_write_5m + u.cache_write_1h,
                cost_usd=cost, cost_source=source, succeeded=True,
                latency_ms=c.latency_ms if i == 0 else None, request_id=c.request_id,
                occurred_at=utcnow()))
        with self._db.session() as s:
            s.add_all(rows)
        self._publish("ai.usage", {"provider": pid, "billing_kind": c.billing_kind,
                                   "cost_usd": str(total) if total is not None else None})
        return total

    def _record_failure(self, pid: str, purpose: str, task_id: str | None,
                        project_id: str | None, exc: ProviderError) -> None:
        if exc.code == "budget":
            return  # refused before calling; audited separately
        with self._db.session() as s:
            s.add(UsageRecord(provider_id=pid,
                              billing_kind="claude_code" if pid == "claude_code" else "api",
                              model_requested=None, model="-", purpose=purpose, task_id=task_id,
                              project_id=project_id, cost_usd=None, cost_source="none",
                              succeeded=False, error_code=exc.code, request_id=exc.request_id,
                              occurred_at=utcnow()))
        self._publish("ai.usage", {"provider": pid, "failed": exc.code})

    # ------------------------------------------------------------------ limits & alerts
    def _api_spend(self, *, since: datetime | None = None, until: datetime | None = None,
                   task_id: str | None = None, project_id: str | None = None) -> Decimal:
        q = select(func.coalesce(func.sum(UsageRecord.cost_usd), 0)).where(
            UsageRecord.billing_kind == "api")
        if since is not None:
            q = q.where(UsageRecord.occurred_at >= since)
        if until is not None:
            q = q.where(UsageRecord.occurred_at < until)
        if task_id is not None:
            q = q.where(UsageRecord.task_id == task_id)
        if project_id is not None:
            q = q.where(UsageRecord.project_id == project_id)
        with self._db.session() as s:
            return Decimal(str(s.scalar(q) or 0))

    def _remaining_task_budget(self, task_id: str | None) -> float | None:
        lim = self._settings.limits.per_task_usd
        if lim is None or task_id is None:
            return None
        return max(0.0, float(lim - self._api_spend(task_id=task_id)))

    def _check_limits(self, task_id: str | None, project_id: str | None, pid: str) -> None:
        if pid != "anthropic":
            return  # Claude Code budgets are passed to the CLI per call (--max-budget-usd)
        lim = self._settings.limits
        mk = month_key()
        checks: list[tuple[str, Decimal | None, Callable[[], Decimal]]] = [
            ("monthly", lim.monthly_usd, lambda: self._api_spend(since=month_start(mk))),
        ]
        if task_id:
            checks.append(("task", lim.per_task_usd, lambda: self._api_spend(task_id=task_id)))
        if project_id:
            checks.append(("project", lim.per_project_usd,
                           lambda: self._api_spend(project_id=project_id)))
        for scope, limit, spent_fn in checks:
            if limit is None:
                continue
            spent = spent_fn()
            if spent >= limit:
                self._audit.record("ai.limit.block", outcome="denied", actor_type="system",
                                   details={"scope": scope, "limit_usd": str(limit),
                                            "spent_usd": str(spent)})
                self._notes.create("ai.limit", f"AI request blocked: {scope} spending limit",
                                   f"${spent:.2f} spent of ${limit:.2f}. Raise the limit in "
                                   "Usage and Billing to continue.", level="error",
                                   task_id=task_id)
                raise ProviderError("budget", f"The {scope} spending limit of ${limit:.2f} "
                                    f"has been reached (${spent:.2f} spent)")

    def _check_alerts(self) -> None:
        lim = self._settings.limits.monthly_usd
        if not lim:
            return
        mk = month_key()
        spent = self._api_spend(since=month_start(mk))
        pct = float(spent / lim * 100)

        class Sent(BaseModel):
            month: str = ""
            pcts: list[int] = Field(default_factory=list)

        sent = self._store.get(ALERTS_KEY, Sent)
        if sent.month != mk:
            sent = Sent(month=mk)
        new = [p for p in sorted(self._settings.limits.alert_pct)
               if pct >= p and p not in sent.pcts]
        if not new:
            return
        p = new[-1]
        self._notes.create("ai.spend_alert", f"AI spending at {p}% of the monthly limit",
                           f"${spent:.2f} of ${lim:.2f} this month (API usage).",
                           level="error" if p >= 100 else "warning")
        sent.pcts = sorted({*sent.pcts, *new})
        self._store.put(ALERTS_KEY, sent)

    # ------------------------------------------------------------------ reports
    def month_summary(self, mk: str) -> dict[str, Any]:
        start, end = month_start(mk), next_month(mk)
        with self._db.session() as s:
            base = select(UsageRecord).where(UsageRecord.occurred_at >= start,
                                             UsageRecord.occurred_at < end)
            rows = list(s.scalars(base))
        def bucket() -> dict[str, Any]:
            return {"requests": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0,
                    "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": Decimal(0),
                    "unpriced_requests": 0}
        by_kind = {"api": bucket(), "claude_code": bucket()}
        by_model: dict[str, dict[str, Any]] = {}
        by_day: dict[str, Decimal] = {}
        for r in rows:
            k = by_kind.setdefault(r.billing_kind, bucket())
            if not r.succeeded:
                k["failed"] += 1
                continue
            if r.latency_ms is not None:  # first part of a call counts as the request
                k["requests"] += 1
            for f in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
                k[f] += getattr(r, f)
            if r.cost_usd is not None:
                k["cost_usd"] += r.cost_usd
            elif r.billing_kind == "api":
                k["unpriced_requests"] += 1
            m = by_model.setdefault(f"{r.billing_kind}:{r.model}", {
                "model": r.model, "billing_kind": r.billing_kind, "input_tokens": 0,
                "output_tokens": 0, "cost_usd": Decimal(0)})
            m["input_tokens"] += r.input_tokens
            m["output_tokens"] += r.output_tokens
            if r.cost_usd is not None:
                m["cost_usd"] += r.cost_usd
            if r.billing_kind == "api" and r.cost_usd is not None:
                day = r.occurred_at.strftime("%Y-%m-%d")
                by_day[day] = by_day.get(day, Decimal(0)) + r.cost_usd
        lim = self._settings.limits.monthly_usd
        def dec(v: Any) -> Any:
            return str(v) if isinstance(v, Decimal) else v
        return {
            "month": mk,
            "api": {k: dec(v) for k, v in by_kind["api"].items()},
            "claude_code": {k: dec(v) for k, v in by_kind["claude_code"].items()},
            "by_model": [{k: dec(v) for k, v in m.items()} for m in
                         sorted(by_model.values(), key=lambda m: -m["cost_usd"])],
            "by_day": [{"day": d, "cost_usd": str(c)} for d, c in sorted(by_day.items())],
            "monthly_limit_usd": str(lim) if lim is not None else None,
            "limit_used_pct": (round(float(by_kind["api"]["cost_usd"] / lim * 100), 1)
                               if lim else None),
        }

    def records(self, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        with self._db.session() as s:
            total = s.scalar(select(func.count()).select_from(UsageRecord)) or 0
            rows = s.scalars(select(UsageRecord).order_by(UsageRecord.occurred_at.desc())
                             .limit(limit).offset(offset)).all()
            out = [{
                "id": r.id, "occurred_at": r.occurred_at.isoformat(), "provider": r.provider_id,
                "billing_kind": r.billing_kind, "model": r.model, "purpose": r.purpose,
                "task_id": r.task_id, "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens, "cache_read_tokens": r.cache_read_tokens,
                "cache_write_tokens": r.cache_write_tokens,
                "cost_usd": str(r.cost_usd) if r.cost_usd is not None else None,
                "cost_source": r.cost_source, "succeeded": r.succeeded,
                "error_code": r.error_code, "latency_ms": r.latency_ms,
            } for r in rows]
            return out, total


def _name(pid: str) -> str:
    return "Claude Code" if pid == "claude_code" else "the Anthropic API"
