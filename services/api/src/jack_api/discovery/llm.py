"""Claude-backed understanding for requirement discovery.

Claude is asked for schema-constrained JSON and every value is checked against the catalogue
before use: unknown categories or slots, and values outside a slot's options, are dropped
rather than trusted. Callers fall back to local rules when this raises ``Unusable``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from jack_api.discovery.catalog import BY_ID, CATEGORIES, Category, Slot
from jack_api.discovery.rules import Value

# complete(prompt, *, purpose, system, json_schema, task_id) -> reply text (JSON)
Completer = Callable[..., dict[str, Any]]

SYSTEM = (
    "You are the requirement-discovery component of JACK, a desktop assistant that builds "
    "software and creative work for its user. You read what the user said and return JSON "
    "only. Record only what the user actually stated or clearly implied; never invent "
    "requirements, names or numbers. If something is not stated, leave it out."
)


class Unusable(Exception):
    """Claude's reply couldn't be used (invalid JSON or nothing valid in it)."""


@dataclass
class ClassifyResult:
    category: str | None
    confidence: float
    alternatives: list[str]
    model: str | None = None


@dataclass
class ExtractResult:
    values: dict[str, tuple[Value, str | None]] = field(default_factory=dict)  # slot -> (v, other)
    conflicts: list[str] = field(default_factory=list)
    model: str | None = None


CLASSIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": [c.id for c in CATEGORIES] + ["unknown"]},
        "confidence": {"type": "number"},
        "alternatives": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["category", "confidence", "alternatives"],
    "additionalProperties": False,
}

EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "values": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slot": {"type": "string"},
                    "values": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["slot", "values"],
                "additionalProperties": False,
            },
        },
        "conflicts": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["values", "conflicts"],
    "additionalProperties": False,
}


def _parse(reply: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(str(reply.get("text") or ""))
    except json.JSONDecodeError as exc:
        raise Unusable("Claude's reply was not valid JSON") from exc
    if not isinstance(data, dict):
        raise Unusable("Claude's reply was not a JSON object")
    return data


def classify(complete: Completer, text: str, task_id: str | None) -> ClassifyResult:
    lines = "\n".join(f"- {c.id}: {c.name} — {c.description}" for c in CATEGORIES)
    prompt = (
        "Which category of work is this request? Choose the single best category id, or "
        "\"unknown\" if it is not a request for work in any of them. Give your confidence "
        "from 0 to 1, and up to three other plausible category ids.\n\n"
        f"Categories:\n{lines}\n\nRequest: {json.dumps(text)}"
    )
    reply = complete(prompt, purpose="discovery.classify", system=SYSTEM,
                     json_schema=CLASSIFY_SCHEMA, task_id=task_id)
    data = _parse(reply)
    cid = data.get("category")
    try:
        conf = max(0.0, min(1.0, float(data.get("confidence", 0))))
    except (TypeError, ValueError):
        conf = 0.0
    raw_alts = data.get("alternatives")
    alts = [a for a in (raw_alts if isinstance(raw_alts, list) else [])
            if isinstance(a, str) and a in BY_ID and a != cid][:3]
    if cid not in BY_ID:
        cid = None
    return ClassifyResult(cid, conf, alts, reply.get("model_served"))


def _slot_line(s: Slot) -> str:
    if s.kind in ("choice", "multi"):
        opts = "; ".join(f"{o.value} = {o.label}" for o in s.options)
        many = "one or more" if s.kind == "multi" else "exactly one"
        extra = " (or the user's own words if none fits)" if s.allow_other else ""
        return f"- {s.id} ({s.label}): {many} of [{opts}]{extra}"
    if s.kind == "bool":
        return f"- {s.id} ({s.label}): \"yes\" or \"no\""
    return f"- {s.id} ({s.label}): free text in the user's words"


def extract(complete: Completer, category: Category, text: str, *, asked: Slot | None,
            known: dict[str, str], task_id: str | None) -> ExtractResult:
    slots = "\n".join(_slot_line(s) for s in category.slots)
    known_lines = "\n".join(f"- {k}: {v}" for k, v in known.items()) or "- (nothing yet)"
    focus = (f"JACK just asked: {json.dumps(asked.question)} (slot {asked.id}).\n"
             if asked else "This is the user's opening request.\n")
    prompt = (
        f"The user wants a {category.noun} ({category.name}). {focus}"
        "From the user's message, fill any of these requirement slots the user stated. Use "
        "option ids exactly as listed. Only include a slot when the message actually says it.\n"
        f"Slots:\n{slots}\n\nAlready known:\n{known_lines}\n\n"
        "Also list any contradictions between the message and what is already known, or within "
        "the message, as short sentences addressed to the user (empty list if none).\n\n"
        f"User's message: {json.dumps(text)}"
    )
    reply = complete(prompt, purpose="discovery.extract", system=SYSTEM,
                     json_schema=EXTRACT_SCHEMA, task_id=task_id)
    data = _parse(reply)
    out = ExtractResult(model=reply.get("model_served"))
    items, conflicts = data.get("values"), data.get("conflicts", [])
    if not isinstance(items, list) or not isinstance(conflicts, list):
        raise Unusable("Claude's reply did not match the schema")
    for item in items:
        if not isinstance(item, dict):
            continue
        slot = category.slot(str(item.get("slot")))
        raw = [str(v).strip() for v in item.get("values") or [] if str(v).strip()]
        if slot is None or not raw:
            continue
        valid = _validate(slot, raw)
        if valid is not None:
            out.values[slot.id] = valid
    out.conflicts = [c.strip()[:300] for c in conflicts if isinstance(c, str) and c.strip()][:3]
    return out


def _validate(slot: Slot, raw: list[str]) -> tuple[Value, str | None] | None:
    ids = {o.value for o in slot.options}
    if slot.kind == "text":
        return raw[0][:500], None
    if slot.kind == "bool":
        v = raw[0].lower()
        return (True, None) if v in ("yes", "true") else (False, None) if v in ("no", "false") \
            else None
    if slot.kind == "choice":
        if raw[0] in ids:
            return raw[0], None
        return ("other", raw[0][:200]) if slot.allow_other else None
    picked = tuple(dict.fromkeys(v for v in raw if v in ids))
    return (picked, None) if picked else None
