"""Requirement discovery engine (Section 6): one question at a time, then a specification.

A session belongs to one task. Each user message is interpreted against the session's pending
question; answers are remembered and never asked again. The task moves through UNDERSTANDING,
REQUIREMENTS (holding in WAITING_FOR_INFORMATION while JACK waits for an answer) and then either
straight to PLANNING (small jobs) or to WAITING_FOR_APPROVAL with the specification.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import func, select

from jack_api.ai.providers import ProviderError
from jack_api.audit import AuditLog
from jack_api.db import Database, RequirementSession, RequirementTurn, Task, utcnow
from jack_api.discovery import llm, rules
from jack_api.discovery.catalog import BY_ID, CATEGORIES, Category, Conflict, Slot
from jack_api.discovery.rules import Value
from jack_api.discovery.spec import build_spec
from jack_api.settings_store import SettingsStore
from jack_api.tasks import HOLD, TaskStatus, TaskStore

log = logging.getLogger(__name__)

SETTINGS_KEY = "discovery.settings"
ACTIVE = ("choosing_category", "asking", "resolving_conflict", "awaiting_approval", "changing")
IDLE_LIMIT = timedelta(minutes=30)
ACTOR = "jack"
MAX_ATTEMPTS = 2
S = TaskStatus


class DiscoverySettings(BaseModel):
    engine: Literal["auto", "local"] = "auto"      # auto: Claude when a provider is set up
    approval: Literal["auto", "always"] = "auto"   # auto: only medium and large jobs
    followup_listen: bool = True                   # keep listening for the answer after a question


class DiscoverySettingsPatch(BaseModel):
    engine: Literal["auto", "local"] | None = None
    approval: Literal["auto", "always"] | None = None
    followup_listen: bool | None = None


class SessionNotFound(Exception):
    pass


class SessionClosed(Exception):
    pass


@dataclass
class Reply:
    session_id: str
    task_id: str
    text: str
    status: str
    expects_answer: bool
    options: list[str] = field(default_factory=list)
    slot: str | None = None
    listen: bool = False


Publisher = Callable[[str, dict[str, Any]], None]
TaskPublisher = Callable[[str, Task], None]


class DiscoveryEngine:
    def __init__(self, db: Database, tasks: TaskStore, audit: AuditLog, store: SettingsStore,
                 publish: Publisher, publish_task: TaskPublisher,
                 complete: llm.Completer | None = None,
                 provider_ready: Callable[[], bool] | None = None) -> None:
        self._db = db
        self._tasks = tasks
        self._audit = audit
        self._store = store
        self._publish = publish
        self._publish_task = publish_task
        self._complete = complete
        self._provider_ready = provider_ready or (lambda: complete is not None)
        self._settings = store.get(SETTINGS_KEY, DiscoverySettings)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ settings
    @property
    def settings(self) -> DiscoverySettings:
        return self._settings

    def update_settings(self, patch: DiscoverySettingsPatch) -> DiscoverySettings:
        merged = self._settings.model_copy(update=patch.model_dump(exclude_none=True))
        self._settings = DiscoverySettings.model_validate(merged.model_dump())
        self._store.put(SETTINGS_KEY, self._settings)
        self._audit.record("settings.change", outcome="allowed", actor_type="user",
                           target="discovery", details=patch.model_dump(exclude_none=True))
        self._publish("discovery.settings", self._settings.model_dump())
        return self._settings

    def engine_status(self) -> dict[str, Any]:
        claude = self._use_claude()
        return {"settings": self._settings.model_dump(), "using": "claude" if claude else "local",
                "detail": None if claude else (
                    "Using JACK's local rules. Set up Claude on the Usage and Billing page for "
                    "better understanding of free-form answers."
                    if self._settings.engine == "auto" else "Local rules chosen in settings.")}

    # ------------------------------------------------------------------ entry points
    def message(self, text: str, *, source: str, session_id: str | None = None,
                continue_active: bool = False) -> Reply:
        """A user utterance: answers a session, or starts a new one."""
        text = " ".join(text.split())
        if not text:
            raise ValueError("Say or type something first")
        with self._lock:
            row: RequirementSession | None = None
            if session_id:
                row = self._load(session_id)
                if row.status not in ACTIVE:
                    raise SessionClosed(f"That conversation is {row.status}")
            elif continue_active:
                row = self._active_row()
            if row is None:
                return self._start(text, source)
            return self._answer(row, text, source)

    def answer_task(self, task_id: str, text: str, source: str) -> Reply:
        with self._lock:
            row = self._by_task(task_id)
            if row.status not in ACTIVE:
                raise SessionClosed(f"That conversation is {row.status}")
            return self._answer(row, " ".join(text.split()), source)

    def set_answer(self, session_id: str, slot_id: str, value: Any) -> Reply:
        """An edit from the UI (explicit slot and value, validated against the catalogue)."""
        with self._lock:
            row = self._load(session_id)
            if row.status in ("cancelled", "blocked"):
                raise SessionClosed(f"That conversation is {row.status}")
            st = row.state
            cat = BY_ID.get(row.category or "")
            slot = cat.slot(slot_id) if cat else None
            if cat is None or slot is None:
                raise ValueError("Unknown requirement")
            v = _coerce(slot, value)
            st["answers"][slot_id] = {"value": _jsonable(v), "source": "user", "engine": "ui"}
            st["pending"] = None
            self._audit.record("requirements.edit", outcome="allowed", actor_type="user",
                               target=f"task:{row.task_id}", details={"slot": slot_id})
            if row.status in ("awaiting_approval", "ready"):
                self._reopen(row, f"Changed {slot.label.lower()} on the Requirements page")
            return self._next(row, source="ui", prefix="")

    def approve(self, session_id: str) -> Reply:
        with self._lock:
            row = self._load(session_id)
            if row.status != "awaiting_approval":
                raise SessionClosed("There's no specification waiting for approval")
            return self._approve(row, "ui")

    def cancel(self, session_id: str, source: str = "ui") -> Reply:
        with self._lock:
            row = self._load(session_id)
            if row.status not in ACTIVE:
                raise SessionClosed(f"That conversation is {row.status}")
            return self._cancel(row, source)

    def get(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            return self._view(self._load(session_id))

    def for_task(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            return self._view(self._by_task(task_id))

    def sessions(self, active_only: bool, limit: int = 20) -> list[dict[str, Any]]:
        with self._db.session() as s:
            q = select(RequirementSession)
            if active_only:
                q = q.where(RequirementSession.status.in_(ACTIVE))
            rows = s.scalars(q.order_by(RequirementSession.updated_at.desc()).limit(limit)).all()
        return [self._view(r, turns=False) for r in rows]

    def active(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._active_row()
            return self._view(row) if row else None

    # ------------------------------------------------------------------ conversation
    def _start(self, text: str, source: str) -> Reply:
        task = self._tasks.create(text, source, None, "local-user")
        self._publish_task("task.created", task)
        self._move(task.id, S.UNDERSTANDING, "Working out what kind of job this is")
        state: dict[str, Any] = {
            "command": text, "source": source, "answers": {}, "asked": [], "pending": None,
            "resolved": [], "claude_conflicts": [], "claude_seen": [], "notes": [],
            "engines": [], "category_source": None, "confidence": 0.0, "offered": [],
            "hinted": False,
        }
        now = utcnow()
        row = RequirementSession(task_id=task.id, status="asking", category=None, state=state,
                                 created_at=now, updated_at=now)
        with self._db.session() as s:
            s.add(row)
            s.flush()
        self._turn(row, "user", text, None, source)
        cid, conf, alts, how = self._classify(text, task.id, state)
        state["confidence"] = conf
        self._audit.record("requirements.start", outcome="allowed", actor_type="system",
                           target=f"task:{task.id}",
                           details={"category": cid, "confidence": conf, "engine": how})
        prefix = ""
        if cid:
            self._set_category(row, cid, how)
            self._extract(row, text, asked=None)
            prefix = _ack(BY_ID[cid])
        else:
            state["offered"] = alts or ["website", "web_app", "research", "automation"]
        self._move(task.id, S.REQUIREMENTS, "Gathering requirements")
        return self._next(row, source=source, prefix=prefix)

    def _answer(self, row: RequirementSession, text: str, source: str) -> Reply:
        st = row.state
        self._turn(row, "user", text, (st.get("pending") or {}).get("slot"), source)
        if rules.wants_cancel(text):
            return self._cancel(row, source)
        pending = st.get("pending") or {}
        kind = pending.get("kind")
        if kind == "approval":
            t = rules.norm(text)
            if rules.matches_any(t, rules.APPROVE) and not rules.matches_any(
                    t, ("change", "not", "wrong", "but")):
                return self._approve(row, source)
            changed = self._apply_change(row, text)
            if changed:
                self._reopen(row, "Changed after review")
                return self._next(row, source=source, prefix="Updated. ")
            row.status = "changing"
            st["pending"] = {"kind": "change", "attempts": 0}
            self._reopen(row, "User asked for changes")
            return self._say(row, "What would you like to change?", source, expects=True,
                             wait=True)
        if kind == "change":
            if self._apply_change(row, text):
                return self._next(row, source=source, prefix="Updated. ")
            pending["attempts"] = pending.get("attempts", 0) + 1
            if pending["attempts"] >= MAX_ATTEMPTS:
                st["pending"] = None
                return self._next(row, source=source, prefix="I couldn't tell what to change, "
                                  "so I've kept the specification as it was. You can also edit "
                                  "it on the Requirements page. ")
            return self._say(row, "Sorry, which part? For example the hosting, the features, or "
                             "the design.", source, expects=True, wait=True)
        if kind == "category":
            cid = self._category_from_answer(row, text)
            if cid is None:
                pending["attempts"] = pending.get("attempts", 0) + 1
                return self._ask_category(row, source, retry=True)
            self._set_category(row, cid, "user")
            self._extract(row, st["command"], asked=None)
            st["pending"] = None
            return self._next(row, source=source, prefix=_ack(BY_ID[cid]))
        if kind == "conflict":
            return self._resolve_conflict(row, text, source)
        if kind == "claude_conflict":
            st["notes"].append(f"{pending.get('message')} — you said: “{text}”")
            st["claude_seen"].append(pending.get("message"))
            st["pending"] = None
            return self._next(row, source=source, prefix="Noted. ")
        # A slot question (or nothing pending).
        cat = self._cat(row)
        if rules.wants_all_defaults(text):
            self._fill_defaults(row, everything=True)
            st["pending"] = None
            st["notes"].append("You asked me to use defaults for the remaining questions.")
            return self._next(row, source=source, prefix="Okay, I'll use sensible defaults. ")
        slot = cat.slot(pending["slot"]) if (cat and pending.get("slot")) else None
        got = self._extract(row, text, asked=slot)
        if slot is None or slot.id in got:
            st["pending"] = None
            return self._next(row, source=source, prefix="")
        pending["attempts"] = pending.get("attempts", 0) + 1
        if pending["attempts"] >= MAX_ATTEMPTS:
            self._store_answer(row, slot, slot.default, "default", None, "local")
            st["notes"].append(f"{slot.label}: I didn't understand the answer, so I used the "
                               "default. You can change it on the Requirements page.")
            st["pending"] = None
            return self._next(row, source=source, prefix="I'll use the usual choice for that. ")
        return self._say(row, _retry_question(slot), source, expects=True, wait=True,
                         options=_option_labels(slot), slot=slot.id)

    # ------------------------------------------------------------------ the next step
    def _next(self, row: RequirementSession, *, source: str, prefix: str) -> Reply:
        st = row.state
        cat = self._cat(row)
        if cat is None:
            return self._ask_category(row, source, prefix=prefix)
        if cat.id == "security_audit" and (st["answers"].get("authorised") or {}).get(
                "value") is False:
            return self._block(row, source, "I can only audit systems you own or have written "
                               "permission to test, so I've stopped here.")
        for c in cat.conflicts:
            key = _conflict_key(c)
            if key not in st["resolved"] and self._conflict_holds(row, c):
                st["pending"] = {"kind": "conflict", "key": key, "attempts": 0}
                row.status = "resolving_conflict"
                return self._say(row, f"{prefix}{c.message} Which would you prefer: "
                                 f"{c.keep_a.lower()}, or {c.keep_b.lower()}?", source,
                                 expects=True, wait=True, options=[c.keep_a, c.keep_b])
        open_c = [m for m in st["claude_conflicts"] if m not in st["claude_seen"]]
        if open_c:
            st["pending"] = {"kind": "claude_conflict", "message": open_c[0]}
            row.status = "resolving_conflict"
            return self._say(row, f"{prefix}{open_c[0]} How should I handle that?", source,
                             expects=True, wait=True)
        for slot in cat.slots:
            if slot.essential and slot.id not in st["answers"] and self._applies(row, slot):
                return self._ask_slot(row, slot, source, prefix)
        return self._finalise(row, source, prefix)

    def _ask_slot(self, row: RequirementSession, slot: Slot, source: str, prefix: str) -> Reply:
        st = row.state
        st["pending"] = {"kind": "slot", "slot": slot.id, "attempts": 0}
        if slot.id not in st["asked"]:
            st["asked"].append(slot.id)
        row.status = "asking"
        hint = ""
        if not st["hinted"]:
            st["hinted"] = True
            hint = " If you're not sure, say “you decide”."
        return self._say(row, f"{prefix}{slot.question}{hint}", source, expects=True, wait=True,
                         options=_option_labels(slot), slot=slot.id)

    def _ask_category(self, row: RequirementSession, source: str, *, prefix: str = "",
                      retry: bool = False) -> Reply:
        st = row.state
        offered: list[str] = st.get("offered") or []
        attempts = (st.get("pending") or {}).get("attempts", 0)
        st["pending"] = {"kind": "category", "attempts": attempts}
        row.status = "choosing_category"
        names = [BY_ID[c].name.lower() for c in offered[:4]]
        if retry and attempts >= MAX_ATTEMPTS:
            q = ("I still can't tell what kind of job this is. Choose one on the Requirements "
                 "page, or say “cancel”.")
        elif len(names) >= 2:
            q = (f"{'Sorry, ' if retry else ''}What kind of job is this: "
                 f"{', '.join(names[:-1])}, or {names[-1]}?")
        else:
            q = ("What kind of job is this? For example a website, an app, research, "
                 "or an automation.")
        return self._say(row, prefix + q, source, expects=True, wait=True,
                         options=[BY_ID[c].name for c in (offered or [c.id for c in CATEGORIES])])

    def _finalise(self, row: RequirementSession, source: str, prefix: str) -> Reply:
        st = row.state
        cat = self._cat(row)
        assert cat is not None
        self._fill_defaults(row, everything=False)
        spec = build_spec(cat, st["answers"], engines=list(dict.fromkeys(st["engines"])),
                          notes=st["notes"], approval_setting=self._settings.approval)
        row.spec = spec
        st["pending"] = None
        self._tasks.rename(row.task_id, spec["title"])
        self._audit.record("requirements.spec", outcome="allowed", actor_type="system",
                           target=f"task:{row.task_id}",
                           details={"category": cat.id, "scale": spec["scope"]["scale"],
                                    "approval_required": spec["approval_required"]})
        n = len(spec["scope"]["components"])
        if spec["approval_required"]:
            st["pending"] = {"kind": "approval"}
            row.status = "awaiting_approval"
            integ = spec["integrations"]
            extra = (f", and it needs {_join([i['name'] for i in integ[:2]])}"
                     + (" among others" if len(integ) > 2 else "")) if integ else ""
            text = (f"{prefix}I have what I need for the {spec['title'][0].lower()}"
                    f"{spec['title'][1:]}. It's a {spec['scope']['scale']} project with {n} "
                    f"components{extra}. The full specification is on the Requirements page. "
                    "Shall I go ahead with it?")
            self._move(row.task_id, S.WAITING_FOR_APPROVAL, "Specification ready for approval")
            return self._say(row, text, source, expects=True, wait=False,
                             options=["Approve", "Change something"])
        row.status = "ready"
        row.approved_at = utcnow()
        self._move(row.task_id, S.PLANNING, "Requirements complete (small job, no approval "
                   "needed)")
        text = (f"{prefix}Thanks, that's everything I need. I've written the specification for "
                f"the {spec['title'][0].lower()}{spec['title'][1:]}. Planning and carrying out "
                "the work arrive in a later version of JACK, so I'll stop there for now.")
        return self._say(row, text, source, expects=False, wait=False)

    def _approve(self, row: RequirementSession, source: str) -> Reply:
        row.status = "ready"
        row.approved_at = utcnow()
        row.state["pending"] = None
        self._move(row.task_id, S.PLANNING, "Specification approved")
        self._audit.record("requirements.approve", outcome="allowed", actor_type="user",
                           target=f"task:{row.task_id}", details={"via": source})
        return self._say(row, "Approved. I've saved the specification. Planning and building "
                         "arrive in a later version of JACK, so the task will wait in planning "
                         "until then.", source, expects=False, wait=False)

    def _cancel(self, row: RequirementSession, source: str) -> Reply:
        row.status = "cancelled"
        row.state["pending"] = None
        self._move(row.task_id, S.CANCELLED, "Cancelled during requirements")
        self._audit.record("requirements.cancel", outcome="allowed", actor_type="user",
                           target=f"task:{row.task_id}", details={"via": source})
        return self._say(row, "Okay, I've cancelled that.", source, expects=False, wait=False)

    def _block(self, row: RequirementSession, source: str, why: str) -> Reply:
        row.status = "blocked"
        row.state["pending"] = None
        row.state["blocked_reason"] = why
        self._move(row.task_id, S.CANCELLED, why)
        self._audit.record("requirements.blocked", outcome="denied", actor_type="system",
                           target=f"task:{row.task_id}", details={"reason": why})
        return self._say(row, why, source, expects=False, wait=False)

    def _reopen(self, row: RequirementSession, reason: str) -> None:
        """Back from a finished or awaiting-approval spec to gathering requirements."""
        task, _ = self._tasks.get(row.task_id)
        if task.status == S.WAITING_FOR_APPROVAL and task.resume_status:
            self._move(row.task_id, TaskStatus(task.resume_status), reason)
            task, _ = self._tasks.get(row.task_id)
        if task.status == S.PLANNING:
            # PLANNING can't go back; the spec is revised in place and the change audited.
            self._audit.record("requirements.revise", outcome="allowed", actor_type="user",
                               target=f"task:{row.task_id}", details={"reason": reason})
        row.approved_at = None
        if row.status in ("awaiting_approval", "ready"):
            row.status = "asking"

    # ------------------------------------------------------------------ understanding
    def _use_claude(self) -> bool:
        return (self._settings.engine == "auto" and self._complete is not None
                and self._provider_ready())

    def _llm_call(self, row_or_state: dict[str, Any], what: str,
                  fn: Callable[[], Any]) -> Any | None:
        if not self._use_claude():
            return None
        try:
            return fn()
        except (ProviderError, llm.Unusable) as exc:
            code = getattr(exc, "code", "invalid_reply")
            note = (f"Claude wasn't available for {what} ({code}); JACK's local rules were "
                    "used instead.")
            if note not in row_or_state["notes"]:
                row_or_state["notes"].append(note)
            log.info("discovery: %s", note)
            return None

    def _classify(self, text: str, task_id: str, st: dict[str, Any]
                  ) -> tuple[str | None, float, list[str], str]:
        res = self._llm_call(st, "understanding the request",
                             lambda: llm.classify(self._complete_fn, text, task_id))
        if res is not None:
            st["engines"].append(f"claude:{res.model}" if res.model else "claude")
            if res.category and res.confidence >= 0.6:
                return res.category, res.confidence, res.alternatives, "claude"
            alts = ([res.category] if res.category else []) + res.alternatives
            return None, res.confidence, alts, "claude"
        st["engines"].append("local")
        local = rules.classify(text)
        return local.category, local.confidence, local.alternatives, "local"

    def _category_from_answer(self, row: RequirementSession, text: str) -> str | None:
        st = row.state
        offered = st.get("offered") or []
        cid = rules.category_from_answer(text, offered)
        if cid:
            return cid
        res = self._llm_call(st, "understanding the request",
                             lambda: llm.classify(self._complete_fn, text, row.task_id))
        return res.category if res is not None else None

    def _extract(self, row: RequirementSession, text: str, asked: Slot | None) -> set[str]:
        """Fill slots from ``text``; returns the slot ids that were set."""
        st = row.state
        cat = self._cat(row)
        if cat is None:
            return set()
        got: set[str] = set()
        known = {k: rules.display(cat.slot(k), _from_json(cat.slot(k), v.get("value")),  # type: ignore[arg-type]
                                  v.get("other"))
                 for k, v in st["answers"].items() if cat.slot(k)}
        res = self._llm_call(st, "understanding your answer",
                             lambda: llm.extract(self._complete_fn, cat, text, asked=asked,
                                                 known=known, task_id=row.task_id))
        if res is not None:
            st["engines"].append(f"claude:{res.model}" if res.model else "claude")
            for sid, (value, other) in res.values.items():
                slot = cat.slot(sid)
                if slot is None:
                    continue
                if asked is None and slot.kind == "text" and slot.id in st["answers"]:
                    continue
                self._store_answer(row, slot, value, "user" if asked and sid == asked.id
                                   else "inferred", other, "claude")
                got.add(sid)
            for c in res.conflicts:
                if c not in st["claude_conflicts"]:
                    st["claude_conflicts"].append(c)
        else:
            st["engines"].append("local")
        if asked is not None and asked.id not in got:
            m = rules.match_slot(asked, text)
            if m.matched:
                self._store_answer(row, asked, m.value, "default" if m.used_default else "user",
                                   m.other, "local")
                got.add(asked.id)
        if res is None and asked is None:
            # Local rules, opening request only: pick up explicit mentions of options. (In an
            # answer to one question, words like "contact" would wrongly fill other slots.)
            for slot in cat.slots:
                if slot.id in st["answers"] or slot.id in got or slot.kind not in (
                        "choice", "multi"):
                    continue
                m = rules.match_slot(slot, text, strict=True)
                if m.matched and m.value:
                    self._store_answer(row, slot, m.value, "inferred", None, "local")
                    got.add(slot.id)
        return got

    def _apply_change(self, row: RequirementSession, text: str) -> bool:
        """A change requested after review: Claude may revise any slot; local rules only
        explicit option mentions."""
        st = row.state
        cat = self._cat(row)
        if cat is None:
            return False
        before = {k: v.get("value") for k, v in st["answers"].items()}
        res = self._llm_call(st, "understanding your change",
                             lambda: llm.extract(self._complete_fn, cat, text, asked=None,
                                                 known={}, task_id=row.task_id))
        changed = False
        if res is not None:
            for sid, (value, other) in res.values.items():
                slot = cat.slot(sid)
                if slot and _jsonable(value) != before.get(sid):
                    self._store_answer(row, slot, value, "user", other, "claude")
                    changed = True
        else:
            for slot in cat.slots:
                if slot.kind not in ("choice", "multi"):
                    continue
                m = rules.match_slot(slot, text, strict=True)
                if m.matched and m.value and _jsonable(m.value) != before.get(slot.id):
                    self._store_answer(row, slot, m.value, "user", None, "local")
                    changed = True
        return changed

    def _complete_fn(self, prompt: str, **kw: Any) -> dict[str, Any]:
        assert self._complete is not None
        return self._complete(prompt, max_tokens=1024, effort="low", **kw)

    # ------------------------------------------------------------------ conflicts
    def _conflict_holds(self, row: RequirementSession, c: Conflict) -> bool:
        return all(self._has_value(row, slot, val) for slot, val in (c.a, c.b))

    def _has_value(self, row: RequirementSession, slot_id: str, val: str) -> bool:
        a = row.state["answers"].get(slot_id)
        if a is None:
            return False
        v = a.get("value")
        return val in v if isinstance(v, list) else v == val

    def _resolve_conflict(self, row: RequirementSession, text: str, source: str) -> Reply:
        st = row.state
        cat = self._cat(row)
        assert cat is not None
        key = st["pending"]["key"]
        c = next(x for x in cat.conflicts if _conflict_key(x) == key)
        t = rules.norm(text)
        pick = rules.ordinal(t, 2)
        if pick is None:
            score_a = _overlap(t, c.keep_a)
            score_b = _overlap(t, c.keep_b)
            pick = 0 if score_a > score_b else 1 if score_b > score_a else None
        if pick is None:
            st["pending"]["attempts"] = st["pending"].get("attempts", 0) + 1
            if st["pending"]["attempts"] < MAX_ATTEMPTS:
                return self._say(row, f"Sorry — {c.keep_a.lower()}, or {c.keep_b.lower()}?",
                                 source, expects=True, wait=True, options=[c.keep_a, c.keep_b])
            pick = 1  # the safer side by convention: every catalogue conflict lists it second
            st["notes"].append(f"{c.message} I chose “{c.keep_b}”; you can change this.")
        slot_id, new = c.fix_keep_a if pick == 0 else c.fix_keep_b
        slot = cat.slot(slot_id)
        assert slot is not None
        if new is None and slot.kind == "multi":
            # Remove the conflicting option from a multi-choice answer.
            remove = c.b[1] if c.b[0] == slot_id else c.a[1]
            cur = st["answers"].get(slot_id, {}).get("value") or []
            self._store_answer(row, slot, tuple(v for v in cur if v != remove), "user", None,
                               "local")
        else:
            self._store_answer(row, slot, new, "user", None, "local")
        st["resolved"].append(key)
        st["pending"] = None
        return self._next(row, source=source, prefix="Okay. ")

    # ------------------------------------------------------------------ helpers
    def _applies(self, row: RequirementSession, slot: Slot) -> bool:
        for dep, allowed in slot.ask_if.items():
            a = row.state["answers"].get(dep)
            if a is None or a.get("value") not in allowed:
                return False
        return True

    def _fill_defaults(self, row: RequirementSession, *, everything: bool) -> None:
        cat = self._cat(row)
        assert cat is not None
        for slot in cat.slots:
            if slot.id in row.state["answers"] or not self._applies(row, slot):
                continue
            if slot.essential and not everything:
                continue
            self._store_answer(row, slot, slot.default, "default", None, "catalogue")

    def _store_answer(self, row: RequirementSession, slot: Slot, value: Value | None,
                      source: str, other: str | None, engine: str) -> None:
        row.state["answers"][slot.id] = {"value": _jsonable(value), "source": source,
                                         "other": other, "engine": engine}

    def _set_category(self, row: RequirementSession, cid: str, how: str) -> None:
        row.category = cid
        row.state["category_source"] = how

    def _cat(self, row: RequirementSession) -> Category | None:
        return BY_ID.get(row.category or "")

    def _move(self, task_id: str, target: TaskStatus, reason: str) -> None:
        """Transition the task, first leaving a hold state (waiting for information or approval)
        when the target is somewhere else, so the timeline stays valid."""
        task, _ = self._tasks.get(task_id)
        if task.status == target:
            return
        if (task.status in HOLD and target not in (S.CANCELLED, S.FAILED)
                and task.resume_status and task.resume_status != target):
            task = self._tasks.transition(task_id, TaskStatus(task.resume_status), reason, ACTOR,
                                          actor_type="system")
            self._publish_task("task.updated", task)
            if task.status == target:
                return
        updated = self._tasks.transition(task_id, target, reason, ACTOR, actor_type="system")
        self._publish_task("task.updated", updated)

    def _say(self, row: RequirementSession, text: str, source: str, *, expects: bool,
             wait: bool, options: list[str] | None = None, slot: str | None = None) -> Reply:
        """Persist JACK's reply and the session, and move the task to wait if asked."""
        if wait:
            self._move(row.task_id, S.WAITING_FOR_INFORMATION, f"Asked: {text[:200]}")
        self._turn(row, "jack", text, slot, None)
        row.state["last_options"] = options or []
        row.updated_at = utcnow()
        with self._db.session() as s:
            db_row = s.get(RequirementSession, row.id)
            assert db_row is not None
            db_row.status = row.status
            db_row.category = row.category
            db_row.state = _copy(row.state)
            db_row.spec = _copy(row.spec) if row.spec is not None else None
            db_row.updated_at = row.updated_at
            db_row.approved_at = row.approved_at
        reply = Reply(session_id=row.id, task_id=row.task_id, text=text, status=row.status,
                      expects_answer=expects, options=options or [], slot=slot,
                      listen=expects and self._settings.followup_listen)
        self._publish("discovery.updated", {"session_id": row.id, "task_id": row.task_id,
                                            "status": row.status})
        return reply

    def _turn(self, row: RequirementSession, role: str, text: str, slot: str | None,
              source: str | None) -> None:
        with self._db.session() as s:
            seq = (s.scalar(select(func.max(RequirementTurn.seq))
                            .where(RequirementTurn.session_id == row.id)) or 0) + 1
            s.add(RequirementTurn(session_id=row.id, seq=seq, role=role, text=text[:4000],
                                  slot=slot, source=source))

    def _load(self, session_id: str) -> RequirementSession:
        with self._db.session() as s:
            row = s.get(RequirementSession, session_id)
            if row is None:
                raise SessionNotFound(session_id)
            row.state = _copy(row.state)
            return row

    def _by_task(self, task_id: str) -> RequirementSession:
        with self._db.session() as s:
            row = s.scalar(select(RequirementSession).where(RequirementSession.task_id == task_id))
            if row is None:
                raise SessionNotFound(task_id)
            row.state = _copy(row.state)
            return row

    def _active_row(self) -> RequirementSession | None:
        cutoff = utcnow() - IDLE_LIMIT
        with self._db.session() as s:
            row = s.scalar(select(RequirementSession)
                           .where(RequirementSession.status.in_(ACTIVE))
                           .order_by(RequirementSession.updated_at.desc()).limit(1))
            if row is None:
                return None
            updated = row.updated_at if row.updated_at.tzinfo else row.updated_at.replace(
                tzinfo=cutoff.tzinfo)
            if updated < cutoff:
                return None
            row.state = _copy(row.state)
            return row

    def _view(self, row: RequirementSession, turns: bool = True) -> dict[str, Any]:
        st = row.state
        cat = self._cat(row)
        pending = st.get("pending") or {}
        question: dict[str, Any] | None = None
        if pending.get("kind") == "slot" and cat:
            slot = cat.slot(pending["slot"])
            if slot:
                question = {"kind": "slot", "slot": slot.id, "label": slot.label,
                            "text": slot.question, "input": slot.kind,
                            "options": [{"value": o.value, "label": o.label}
                                        for o in slot.options],
                            "default": _jsonable(slot.default)}
        elif pending.get("kind"):
            question = {"kind": pending["kind"],
                        "options": [{"value": o, "label": o} for o in st.get("last_options", [])]}
        answers = []
        if cat:
            for slot in cat.slots:
                a = st["answers"].get(slot.id)
                if a is None:
                    continue
                answers.append({"slot": slot.id, "label": slot.label, "input": slot.kind,
                                "value": a.get("value"), "source": a.get("source"),
                                "display": rules.display(slot, _from_json(slot, a.get("value")),
                                                         a.get("other")),
                                "options": [{"value": o.value, "label": o.label}
                                            for o in slot.options]})
        out: dict[str, Any] = {
            "id": row.id, "task_id": row.task_id, "status": row.status,
            "category": row.category, "category_name": cat.name if cat else None,
            "category_source": st.get("category_source"), "command": st.get("command"),
            "question": question, "answers": answers, "spec": row.spec,
            "notes": st.get("notes", []), "blocked_reason": st.get("blocked_reason"),
            "created_at": row.created_at, "updated_at": row.updated_at,
            "approved_at": row.approved_at,
        }
        if turns:
            with self._db.session() as s:
                rows = s.scalars(select(RequirementTurn)
                                 .where(RequirementTurn.session_id == row.id)
                                 .order_by(RequirementTurn.seq)).all()
                out["turns"] = [{"role": t.role, "text": t.text, "slot": t.slot,
                                 "source": t.source, "at": t.created_at} for t in rows]
        return out


# ---------------------------------------------------------------------------- module helpers
def _ack(cat: Category) -> str:
    if cat.small_by_nature:
        return "Sure. "
    if cat.id in ("infrastructure", "security_audit", "automation", "video_production"):
        return f"Certainly, I'll help with the {cat.noun}. "
    return (f"Certainly. I'll handle the development of the {cat.noun}. Let me understand your "
            "requirements first. ")


def _option_labels(slot: Slot) -> list[str]:
    if slot.kind == "bool":
        return ["Yes", "No"]
    return [o.label for o in slot.options]


def _retry_question(slot: Slot) -> str:
    labels = _option_labels(slot)
    if slot.kind == "text":
        return f"Sorry, I didn't catch that. {slot.question}"
    if len(labels) > 1:
        first = ", ".join(x.lower() for x in labels[:-1])
        return f"Sorry, I didn't catch that. You can say {first}, or {labels[-1].lower()}."
    return f"Sorry, I didn't catch that. {slot.question}"


def _join(items: list[str]) -> str:
    items = [i[0].lower() + i[1:] if i[:2] != i[:2].upper() else i for i in items]
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _conflict_key(c: Conflict) -> str:
    return f"{c.a[0]}={c.a[1]}|{c.b[0]}={c.b[1]}"


def _overlap(text_n: str, label: str) -> int:
    stop = {"it", "on", "the", "a", "and", "with", "for", "my", "this", "keep", "put", "add",
            "i", "to", "of", "only", "now"}
    words = {w for w in rules.norm(label).split() if w not in stop}
    return sum(1 for w in words if rules.has(text_n, w))


def _jsonable(v: Any) -> Any:
    return list(v) if isinstance(v, tuple) else v


def _from_json(slot: Slot | None, v: Any) -> Value | None:
    if v is None:
        return None
    if isinstance(v, list):
        return tuple(v)
    return v  # type: ignore[no-any-return]


def _copy(d: Any) -> Any:
    import copy
    return copy.deepcopy(d)


def _coerce(slot: Slot, value: Any) -> Value:
    if slot.kind == "bool":
        if not isinstance(value, bool):
            raise ValueError("Expected yes or no")
        return value
    if slot.kind == "text":
        v = str(value or "").strip()
        if not v or len(v) > 500:
            raise ValueError("Enter up to 500 characters")
        return v
    ids = {o.value for o in slot.options}
    if slot.kind == "choice":
        if value not in ids:
            raise ValueError("Not one of the options")
        return str(value)
    if not isinstance(value, list) or any(v not in ids for v in value):
        raise ValueError("Not one of the options")
    return tuple(dict.fromkeys(value))


def reply_dict(r: Reply) -> dict[str, Any]:
    return asdict(r)
