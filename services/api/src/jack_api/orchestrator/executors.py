"""Step executors available in Milestone 6.

* ``reasoning.document``: Claude writes a deliverable (an answer, a document, an architecture,
  a plan) from the approved specification and earlier steps; it is saved as a Markdown file in
  the task's workspace and recorded as an artifact.
* ``deliver``: assembles the completion summary from the steps and artifacts.
* ``capability.*``: work that needs a capability JACK doesn't have yet. These never pretend to
  run: they report which capability and milestone they need, and the workflow waits there.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jack_api.ai.providers import ProviderError

# kind -> (what's needed, milestone)
CAPABILITIES: dict[str, tuple[str, int]] = {
    "capability.agents": ("the multi-agent system", 7),
    "capability.github": ("GitHub access", 9),
    "capability.ssh": ("Ubuntu server connections over SSH", 10),
    "capability.build": ("autonomous development with Claude Code", 11),
    "capability.test": ("automated testing and repair", 12),
    "capability.deploy": ("staging and production deployment", 13),
    "capability.creative": ("an image or video generation provider", 14),
    "capability.windows": ("Windows and browser automation", 15),
}


@dataclass
class StepContext:
    task_id: str
    title: str
    spec: dict[str, Any]
    step: dict[str, Any]
    previous: list[dict[str, Any]]           # finished steps: key, title, output
    workspace: Path
    complete: Callable[..., dict[str, Any]] | None   # AIService.complete
    cancelled: Callable[[], bool] = lambda: False


@dataclass
class StepResult:
    output: dict[str, Any]
    artifacts: list[dict[str, Any]] = field(default_factory=list)  # name, path, kind


class Blocked(Exception):
    """The step can't run here yet; ``reason`` is shown to the user."""

    def __init__(self, reason: str, milestone: int | None = None) -> None:
        super().__init__(reason)
        self.milestone = milestone


Executor = Callable[[StepContext], StepResult]

USER_FIXABLE = {
    "not_configured": "Needs Claude: set up the Anthropic API or Claude Code in Usage and "
                      "Billing, then resume",
    "auth": "Claude rejected the API key: update it in Usage and Billing, then resume",
    "permission": "The API key isn't allowed to do this: check it in Usage and Billing, then "
                  "resume",
    "budget": "A spending limit was reached: raise it in Usage and Billing, then resume",
}


def availability(kind: str, *, reasoning_ready: bool,
                 registry: dict[str, Executor]) -> tuple[bool, str | None]:
    if kind in CAPABILITIES:
        what, milestone = CAPABILITIES[kind]
        return False, f"Needs {what}, which arrives in Milestone {milestone}"
    if kind == "reasoning.document" and not reasoning_ready:
        return False, ("Needs Claude: set up the Anthropic API or Claude Code in Usage and "
                       "Billing, then resume")
    if kind not in registry:
        return False, f"No executor for '{kind}'"
    return True, None


def _spec_text(spec: dict[str, Any]) -> str:
    lines = [f"Title: {spec.get('title')}", f"Category: {spec.get('category_name')}",
             f"Summary: {spec.get('summary')}"]
    for item in spec.get("requirements", []) + spec.get("assumptions", []):
        tag = " (assumed default)" if item.get("source") == "default" else ""
        lines.append(f"- {item['label']}: {item['display']}{tag}")
    if spec.get("integrations"):
        lines.append("Integrations: " + ", ".join(i["name"] for i in spec["integrations"]))
    if (spec.get("hosting") or {}).get("display"):
        lines.append(f"Hosting: {spec['hosting']['display']}")
    for n in spec.get("notes", []):
        lines.append(f"Note: {n}")
    return "\n".join(lines)


SYSTEM = (
    "You are part of JACK, a desktop assistant that delivers work for its user. Write the "
    "requested deliverable in Markdown, complete and ready to use. Base it only on the "
    "specification and earlier results provided; where something isn't specified, say what you "
    "assumed. Do not claim to have run code, contacted anyone or checked live sources."
)


def reasoning_document(ctx: StepContext) -> StepResult:
    if ctx.complete is None:
        raise Blocked("Needs Claude: set up a provider in Usage and Billing, then resume")
    instr = ctx.step.get("instructions") or ""
    m = re.match(r"\[artifact:([\w.\-]+)\]\s*(.*)", instr, re.S)
    name, task_text = (m.group(1), m.group(2)) if m else (f"{ctx.step['key']}.md", instr)
    earlier = "\n\n".join(
        f"## Earlier step: {p['title']}\n{(p.get('output') or {}).get('excerpt', '')}"
        for p in ctx.previous if (p.get("output") or {}).get("excerpt"))
    prompt = (f"Specification:\n{_spec_text(ctx.spec)}\n\n"
              + (f"{earlier}\n\n" if earlier else "")
              + f"Your task — {ctx.step['title']}:\n{task_text}")
    try:
        reply = ctx.complete(prompt, purpose="task.step", system=SYSTEM, task_id=ctx.task_id,
                             max_tokens=8000, effort="medium")
    except ProviderError as exc:
        # Things only the user can fix pause the task instead of failing it; transient errors
        # (rate limits, outages, timeouts) are retried.
        if exc.code in USER_FIXABLE:
            raise Blocked(USER_FIXABLE[exc.code] + f" ({exc})") from exc
        raise
    text = str(reply.get("text") or "").strip()
    if not text:
        raise RuntimeError("Claude returned an empty document")
    ctx.workspace.mkdir(parents=True, exist_ok=True)
    path = ctx.workspace / name
    path.write_text(text + "\n", encoding="utf-8")  # same name on retry: idempotent
    return StepResult(
        output={"artifact": name, "chars": len(text), "excerpt": text[:4000],
                "model": reply.get("model_served"), "cost_usd": reply.get("cost_usd")},
        artifacts=[{"name": name, "path": str(path), "kind": "document"}])


def deliver(ctx: StepContext) -> StepResult:
    docs = [p for p in ctx.previous if (p.get("output") or {}).get("artifact")]
    lines = [f"# {ctx.title}", "", "## What JACK delivered", ""]
    if docs:
        lines += [f"- **{p['title']}** — `{p['output']['artifact']}`" for p in docs]
    else:
        lines.append("- No documents were produced.")
    lines += ["", f"Files are in `{ctx.workspace}`."]
    text = "\n".join(lines) + "\n"
    ctx.workspace.mkdir(parents=True, exist_ok=True)
    path = ctx.workspace / "summary.md"
    path.write_text(text, encoding="utf-8")
    first = (f"Delivered {len(docs)} document{'s' if len(docs) != 1 else ''}: "
             + ", ".join(p["output"]["artifact"] for p in docs)) if docs else "Completed."
    return StepResult(output={"summary": first, "excerpt": text},
                      artifacts=[{"name": "summary.md", "path": str(path), "kind": "summary"}])


def default_registry() -> dict[str, Executor]:
    return {"reasoning.document": reasoning_document, "deliver": deliver}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
