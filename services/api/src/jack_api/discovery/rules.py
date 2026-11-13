"""Deterministic local understanding: keyword classification and answer matching.

Used when no Claude provider is set up, when the user chooses local mode, and for one turn when
a Claude call fails. It is intentionally conservative: it only fills a slot when an option's
words appear in what the user said, and otherwise asks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jack_api.discovery.catalog import BY_ID, CATEGORIES, DEFAULT_PHRASES, Category, Slot

Value = str | tuple[str, ...] | bool


def norm(text: str) -> str:
    t = text.lower().replace("’", "'").replace("‘", "'")
    t = re.sub(r"[^a-z0-9'.#+\- ]+", " ", t)
    return " " + re.sub(r"\s+", " ", t).strip(" .") + " "


def has(text_n: str, phrase: str) -> bool:
    """Whole-word / whole-phrase match on normalised text."""
    p = norm(phrase).strip()
    pattern = r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])"
    return bool(p) and re.search(pattern, text_n) is not None


# --------------------------------------------------------------------------- classification
@dataclass
class Classification:
    category: str | None
    confidence: float
    alternatives: list[str]


def classify(text: str) -> Classification:
    t = norm(text)
    scores: list[tuple[float, str]] = []
    for c in CATEGORIES:
        score = sum(w for kw, w in c.keywords if has(t, kw))
        if score > 0:
            scores.append((score, c.id))
    scores.sort(reverse=True)
    if not scores:
        return Classification(None, 0.0, [])
    top, cid = scores[0]
    second = scores[1][0] if len(scores) > 1 else 0.0
    confidence = round(min(1.0, top / 4) * (top - second) / top, 2) if top else 0.0
    alts = [c for _, c in scores[1:4]]
    # A clear winner needs a strong keyword and a margin over the runner-up.
    if top >= 2.5 and (top - second) >= 1.5:
        return Classification(cid, max(confidence, 0.6), alts)
    return Classification(None, confidence, [cid, *alts][:4])


COMMAND_VERBS = ("build", "create", "make", "write", "design", "develop", "research", "automate",
                 "set up", "setup", "deploy", "connect", "generate", "edit", "produce", "audit",
                 "run a", "do a", "i need", "i want", "we need", "can you", "could you")


def looks_like_new_command(text: str) -> bool:
    """A fresh request ("Jack, create a logo…") rather than an answer to a question."""
    t = norm(text)
    t = re.sub(r"^ (hey |ok |okay )?jack,? ", " ", t)
    starts = any(t.startswith(f" {v} ") for v in COMMAND_VERBS)
    return starts and classify(text).category is not None


def category_from_answer(text: str, offered: list[str]) -> str | None:
    """Resolve the user's reply to "which kind of job is this?"."""
    t = norm(text)
    idx = ordinal(t, len(offered))
    if idx is not None:
        return offered[idx]
    for cid in offered or [c.id for c in CATEGORIES]:
        c = BY_ID[cid]
        if has(t, c.name) or has(t, c.noun):
            return cid
    result = classify(text)
    if result.category:
        return result.category
    if result.alternatives and (not offered or result.alternatives[0] in offered):
        return result.alternatives[0]
    return None


# --------------------------------------------------------------------------- control intents
CANCEL = ("cancel", "never mind", "nevermind", "forget it", "stop this", "abort", "scrap that")
ALL_DEFAULTS = ("use defaults", "use the defaults", "use your defaults", "defaults for the rest",
                "decide the rest", "you decide the rest", "fill in the rest", "just build it",
                "use sensible defaults", "rest is up to you", "decide everything")
APPROVE = ("approve", "approved", "looks good", "go ahead", "yes go ahead", "that's right",
           "that is right", "correct", "yes", "yep", "sounds good", "perfect", "confirm")
REJECT = ("no", "change", "not right", "wrong", "that's wrong", "edit")
YES = ("yes", "yeah", "yep", "sure", "correct", "of course", "definitely", "please do", "i do",
       "we do", "right", "affirmative", "ok", "okay")
NO = ("no", "nope", "not", "don't", "do not", "nah", "negative")
NONE = ("none", "nothing", "no thanks", "none of them", "neither", "not needed", "no")
ALL = ("all", "all of them", "everything", "all of those", "the lot")
ORDINALS = (("first", "one", "1", "1st"), ("second", "two", "2", "2nd"),
            ("third", "three", "3", "3rd"), ("fourth", "four", "4", "4th"),
            ("fifth", "five", "5", "5th"), ("sixth", "six", "6", "6th"))


def matches_any(text_n: str, phrases: tuple[str, ...]) -> bool:
    return any(has(text_n, p) for p in phrases)


def wants_cancel(text: str) -> bool:
    return matches_any(norm(text), CANCEL)


def wants_all_defaults(text: str) -> bool:
    return matches_any(norm(text), ALL_DEFAULTS)


def wants_default(text: str) -> bool:
    return matches_any(norm(text), DEFAULT_PHRASES)


def ordinal(text_n: str, n: int) -> int | None:
    """'the second one' -> 1. Only when the reply is short (an ordinal, not a sentence)."""
    if len(text_n.split()) > 4:
        return None
    for i, words in enumerate(ORDINALS[:n]):
        if any(has(text_n, f"the {w}") or has(text_n, f"{w} one") or text_n.strip() == w
               for w in words):
            return i
    return None


# --------------------------------------------------------------------------- slot answers
FILLERS = re.compile(r"^(it's|it is|its|we're|we are|i'm|i am|they're|the name is|it's called|"
                     r"it is called|called|named|we're called|the company is|our company is|"
                     r"my company is|the business is|the company's|our name is|my name is|"
                     r"the name's|um|uh|well|so|basically|okay|ok)\s+", re.I)


@dataclass
class Match:
    value: Value | None
    matched: bool
    used_default: bool = False
    other: str | None = None   # free-text answer kept for allow_other slots


def strip_fillers(text: str) -> str:
    out = text.strip()
    for _ in range(4):
        new = FILLERS.sub("", out).strip()
        if new == out:
            break
        out = new
    return out.strip(" .,!")


def match_slot(slot: Slot, text: str, *, strict: bool = False) -> Match:
    """Interpret ``text`` as an answer to ``slot``.

    ``strict`` is used when scanning the opening command for facts: only explicit keyword hits
    count, never defaults, ordinals or free text.
    """
    t = norm(text)
    if not strict and wants_default(text):
        return Match(slot.default if slot.default is not None else None, True, used_default=True)
    if slot.kind == "bool":
        if strict:
            return Match(None, False)
        no = matches_any(t, NO)
        yes = matches_any(t, YES)
        if yes and not no:
            return Match(True, True)
        if no:
            return Match(False, True)
        return Match(None, False)
    if slot.kind == "text":
        if strict:
            return Match(None, False)
        clean = strip_fillers(text)
        return Match(clean, bool(clean)) if clean else Match(None, False)
    hits = [o.value for o in slot.options
            if has(t, o.label) or has(t, o.value.replace("_", " "))
            or any(has(t, k) for k in o.keywords)]
    if slot.kind == "choice":
        if not strict:
            idx = ordinal(t, len(slot.options))
            if idx is not None:
                return Match(slot.options[idx].value, True)
        if len(hits) == 1 or (hits and strict):
            return Match(hits[0], True)
        if len(hits) > 1:
            # Prefer the option whose own label appears; otherwise it's ambiguous.
            exact = [o.value for o in slot.options if o.value in hits and has(t, o.label)]
            if len(exact) == 1:
                return Match(exact[0], True)
            return Match(None, False)
        if slot.allow_other and not strict:
            clean = strip_fillers(text)
            if clean:
                return Match("other", True, other=clean)
        return Match(None, False)
    # multi
    if not strict:
        if matches_any(t, ALL) and not hits:
            return Match(tuple(o.value for o in slot.options), True)
        if not hits and matches_any(t, NONE):
            return Match((), True)
    if hits:
        return Match(tuple(dict.fromkeys(hits)), True)
    return Match(None, False)


def display(slot: Slot, value: Value | None, other: str | None = None) -> str:
    if value is None:
        return "—"
    if slot.kind == "bool":
        return "Yes" if value else "No"
    if slot.kind == "text":
        return str(value)
    if slot.kind == "choice":
        if value == "other":
            return other or "Other"
        o = slot.option(str(value))
        return o.label if o else str(value)
    vals = list(value) if isinstance(value, (tuple, list)) else [str(value)]
    if not vals:
        return "None"
    return ", ".join((slot.option(v).label if slot.option(v) else v) for v in vals)  # type: ignore[union-attr]


def category_or_none(cid: str | None) -> Category | None:
    return BY_ID.get(cid) if cid else None
