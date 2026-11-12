"""Wake-word detection ("Jack" / "Hey Jack"), local only.

Detectors are pluggable. Shipped engine:

* ``keyword-asr`` — VAD finds an utterance; the first ``WAKE_WINDOW_S`` seconds are
  transcribed locally with Whisper tiny.en and matched against the wake phrase. Uses only
  MIT-licensed code and weights, so it can ship commercially.

Not shipped: an openWakeWord engine. openWakeWord's code is Apache-2.0, but its pre-trained
models are CC BY-NC-SA 4.0 (non-commercial) and none exists for "Jack". It needs a custom
trained model (decision D-3); the ``WakeDetector`` protocol is the slot it plugs into.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from jack_api.voice.asr import WAKE_MODEL, Recognizer
from jack_api.voice.audio import SAMPLE_RATE

WAKE_WINDOW_S = 2.5
GREETINGS = ("hey", "hi", "ok", "okay", "hello", "yo")
BASE_WORDS = ("jack",)
LOOSE_WORDS = ("jacks", "jack's", "jak", "jac")  # common mis-transcriptions
LOOSER_WORDS = ("jacques", "jock")


@dataclass(frozen=True)
class WakeDecision:
    detected: bool
    transcript: str
    remainder: str  # text after the wake phrase (an inline command), possibly ""
    reason: str


class WakeDetector(Protocol):
    engine: str

    def available(self) -> tuple[bool, str | None]: ...
    def check(self, audio: np.ndarray, sensitivity: float) -> WakeDecision: ...


def wake_words(sensitivity: float) -> tuple[str, ...]:
    words: tuple[str, ...] = BASE_WORDS
    if sensitivity >= 0.5:
        words += LOOSE_WORDS
    if sensitivity >= 0.7:
        words += LOOSER_WORDS
    return words


def _pattern(sensitivity: float) -> re.Pattern[str]:
    greet = "|".join(GREETINGS)
    words = "|".join(re.escape(w) for w in wake_words(sensitivity))
    # Wake phrase must open the utterance: "Jack", "Hey Jack", "OK, Jack" ...
    return re.compile(rf"^\W*(?:(?:{greet})\W+)?(?:{words})(?=\W|$)\W*(?P<rest>.*)$",
                      re.IGNORECASE | re.DOTALL)


def split_wake(text: str, sensitivity: float) -> tuple[bool, str]:
    """Return (matched, remainder) for a transcript."""
    m = _pattern(sensitivity).match(text.strip())
    if not m:
        return False, ""
    return True, m.group("rest").strip()


def confidence_ok(avg_logprob: float, no_speech_prob: float, sensitivity: float) -> bool:
    """Higher sensitivity accepts less confident transcriptions."""
    return avg_logprob >= -(0.4 + 1.6 * sensitivity) and no_speech_prob <= 0.5 + 0.4 * sensitivity


class KeywordAsrDetector:
    engine = "keyword-asr"

    def __init__(self, recognizer: Recognizer) -> None:
        self._asr = recognizer

    def available(self) -> tuple[bool, str | None]:
        if self._asr.available(WAKE_MODEL):
            return True, None
        return False, f"Download the {WAKE_MODEL} speech model to enable the wake word"

    def check(self, audio: np.ndarray, sensitivity: float) -> WakeDecision:
        window = audio[: int(WAKE_WINDOW_S * SAMPLE_RATE)]
        t = self._asr.transcribe(window, WAKE_MODEL)
        matched, rest = split_wake(t.text, sensitivity)
        if not matched:
            return WakeDecision(False, t.text, "", "no wake phrase")
        if not confidence_ok(t.avg_logprob, t.no_speech_prob, sensitivity):
            return WakeDecision(False, t.text, "", "low confidence")
        return WakeDecision(True, t.text, rest, "matched")
