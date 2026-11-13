"""Turn discovery answers into a structured project specification (Section 6)."""

from __future__ import annotations

from typing import Any

from jack_api.discovery.catalog import Category
from jack_api.discovery.rules import Value, display

# What JACK itself will need for each kind of work, and when that capability arrives.
# Shown honestly in the specification instead of implying JACK can already do it.
CAPABILITIES: dict[str, tuple[str, int]] = {
    "plan": ("Planning and task orchestration", 6),
    "build": ("Autonomous development with Claude Code", 11),
    "test": ("Automated testing and repair", 12),
    "deploy": ("Staging and production deployment", 13),
    "ssh": ("Ubuntu server connections over SSH", 10),
    "github": ("GitHub repositories", 9),
    "creative": ("Image generation and editing providers", 14),
    "windows": ("Windows and browser automation", 15),
}

SOFTWARE = {"website", "web_app", "windows_app", "android_app", "ios_app", "api", "crm", "erp",
            "hrms", "trading_app", "ai_platform"}


def _vals(v: Value | None) -> list[str]:
    if v is None or isinstance(v, bool):
        return []
    return [str(x) for x in v] if isinstance(v, (tuple, list)) else [str(v)]


def scale_for(category: Category, components: list[str]) -> str:
    if category.small_by_nature or len(components) <= 3:
        return "small"
    return "medium" if len(components) <= 7 else "large"


def build_spec(category: Category, answers: dict[str, dict[str, Any]], *,
               engines: list[str], notes: list[str], approval_setting: str) -> dict[str, Any]:
    components: list[str] = list(category.base_components)
    integrations: dict[str, str] = {}
    requirements: list[dict[str, Any]] = []
    assumptions: list[dict[str, Any]] = []
    open_questions: list[str] = []
    for slot in category.slots:
        a = answers.get(slot.id)
        if a is None:
            continue
        value: Value | None = _to_value(slot.kind, a.get("value"))
        item = {"slot": slot.id, "label": slot.label, "section": slot.section,
                "value": a.get("value"), "display": display(slot, value, a.get("other")),
                "source": a.get("source", "user")}
        if value is None and a.get("source") == "default":
            open_questions.append(slot.question)
            item["display"] = "To be decided"
        (assumptions if a.get("source") == "default" else requirements).append(item)
        for v in _vals(value):
            o = slot.option(v)
            if o is None:
                continue
            components.extend(o.components)
            for name in o.integrations:
                integrations.setdefault(name, f"{slot.label}: {o.label}")
    components = list(dict.fromkeys(components))
    scale = scale_for(category, components)
    hosting = _hosting(category, answers)
    caps = _capabilities(category, answers)
    title = _title(category, answers)
    approval_required = approval_setting == "always" or scale != "small"
    return {
        "version": 1,
        "title": title,
        "category": category.id,
        "category_name": category.name,
        "summary": _summary(category, requirements + assumptions),
        "requirements": requirements,
        "assumptions": assumptions,
        "open_questions": open_questions,
        "scope": {
            "scale": scale,
            "components": components,
            "rationale": (f"{len(components)} components"
                          + ("; this kind of job is a single deliverable"
                             if category.small_by_nature else "")),
        },
        "integrations": [{"name": n, "reason": r} for n, r in integrations.items()],
        "hosting": hosting,
        "dependencies": [{"capability": CAPABILITIES[c][0], "milestone": CAPABILITIES[c][1],
                          "available": False} for c in caps],
        "engines": engines,
        "notes": notes,
        "approval_required": approval_required,
    }


def _to_value(kind: str, raw: Any) -> Value | None:
    if raw is None:
        return None
    if kind == "multi":
        return tuple(raw) if isinstance(raw, (list, tuple)) else (str(raw),)
    if kind == "bool":
        return bool(raw)
    return str(raw)


def _hosting(category: Category, answers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    slot = category.slot("hosting") or category.slot("runs_where")
    if slot is None:
        return {"required": category.deployable, "choice": None,
                "display": "Not needed" if not category.deployable else "To be decided"}
    a = answers.get(slot.id) or {}
    v = a.get("value")
    return {"required": True, "choice": v,
            "display": display(slot, str(v) if v is not None else None, a.get("other")),
            "source": a.get("source")}


def _capabilities(category: Category, answers: dict[str, dict[str, Any]]) -> list[str]:
    caps = ["plan"]
    cid = category.id
    hosting = (answers.get("hosting") or answers.get("runs_where") or {}).get("value")
    if cid in SOFTWARE:
        caps += ["build", "test"]
        if hosting in ("own_server", "managed"):
            caps.append("deploy")
    if hosting in ("own_server", "server") or cid == "infrastructure":
        caps.append("ssh")
    if cid == "security_audit":
        scope = _vals(_to_value("multi", (answers.get("scope") or {}).get("value")))
        if "server" in scope:
            caps.append("ssh")
        if "code" in scope:
            caps.append("github")
    if cid in ("image_generation", "photo_editing", "video_production"):
        caps.append("creative")
    if cid == "automation":
        caps.append("windows")
    if cid == "website" and (answers.get("branding") or {}).get("value") == "design":
        caps.append("creative")
    return list(dict.fromkeys(caps))


NAME_SLOTS = ("business_name", "name", "organisation", "subject", "problem", "process",
              "question", "purpose", "target")


def _title(category: Category, answers: dict[str, dict[str, Any]]) -> str:
    noun = category.noun[0].upper() + category.noun[1:]
    if category.id == "website":
        st = (answers.get("site_type") or {}).get("value")
        noun = {"corporate": "Corporate website", "portal": "Customer portal",
                "platform": "Business platform"}.get(str(st), noun)
        if (answers.get("purpose") or {}).get("value") == "shop":
            noun = "Online shop"
    for sid in NAME_SLOTS:
        slot = category.slot(sid)
        a = answers.get(sid)
        if slot is None or not a or a.get("source") == "default" or slot.kind != "text":
            continue
        v = str(a.get("value") or "").strip()
        if v:
            short = v if len(v) <= 48 else v[:47].rstrip() + "…"
            return f"{noun} for {short}" if sid in ("business_name", "name", "organisation",
                                                     "target") else f"{noun}: {short}"
    return noun


def _summary(category: Category, items: list[dict[str, Any]]) -> str:
    order = {s.id: i for i, s in enumerate(category.slots)}
    parts = [f"{i['label']}: {i['display']}" for i in sorted(items, key=lambda i: order[i["slot"]])
             if i["display"] not in ("—", "None", "To be decided")]
    return f"{category.name}. " + "; ".join(parts[:6]) + ("." if parts else "")
