"""Small DSP helpers: noise filtering and speech segmentation."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from jack_api.voice.audio import FRAME, SAMPLE_RATE

FRAME_MS = FRAME * 1000 / SAMPLE_RATE  # 32 ms


class HighPass:
    """First-order high-pass filter (default 80 Hz): removes DC offset, mains hum and
    low-frequency rumble before VAD/ASR. Stateful across frames."""

    def __init__(self, cutoff_hz: float = 80.0, rate: int = SAMPLE_RATE) -> None:
        rc = 1.0 / (2 * math.pi * cutoff_hz)
        dt = 1.0 / rate
        self.alpha = rc / (rc + dt)
        self._prev_x = 0.0
        self._prev_y = 0.0

    def __call__(self, frame_i16: np.ndarray) -> np.ndarray:
        x = frame_i16.astype(np.float32) / 32768.0
        y = np.empty_like(x)
        a = self.alpha
        px, py = self._prev_x, self._prev_y
        for i in range(x.shape[0]):  # 512 samples per 32 ms frame: cheap enough
            py = a * (py + x[i] - px)
            px = float(x[i])
            y[i] = py
        self._prev_x, self._prev_y = px, py
        return y

    def reset(self) -> None:
        self._prev_x = self._prev_y = 0.0


@dataclass
class Segment:
    audio: np.ndarray  # float32, 16 kHz
    duration_s: float
    truncated: bool  # hit the maximum length rather than ending in silence


@dataclass
class Segmenter:
    """Turns per-frame speech probabilities into utterances.

    Speech starts after ``start_frames`` consecutive voiced frames (with ``pre_roll_ms`` of
    audio kept from before the start) and ends after ``end_silence_ms`` of silence or at
    ``max_s``.
    """

    threshold: float = 0.5
    start_frames: int = 2
    end_silence_ms: float = 700
    pre_roll_ms: float = 320
    max_s: float = 30.0
    min_speech_ms: float = 250
    _pre: deque[np.ndarray] = field(default_factory=deque, init=False)
    _buf: list[np.ndarray] = field(default_factory=list, init=False)
    _voiced_run: int = field(default=0, init=False)
    _silence_ms: float = field(default=0.0, init=False)
    _speech_ms: float = field(default=0.0, init=False)
    in_speech: bool = field(default=False, init=False)

    def reset(self) -> None:
        self._pre.clear()
        self._buf.clear()
        self._voiced_run = 0
        self._silence_ms = 0.0
        self._speech_ms = 0.0
        self.in_speech = False

    def push(self, frame: np.ndarray, prob: float) -> Segment | None:
        voiced = prob >= self.threshold
        if not self.in_speech:
            self._pre.append(frame)
            while len(self._pre) * FRAME_MS > self.pre_roll_ms:
                self._pre.popleft()
            self._voiced_run = self._voiced_run + 1 if voiced else 0
            if self._voiced_run >= self.start_frames:
                self.in_speech = True
                self._buf = list(self._pre)
                self._pre.clear()
                self._silence_ms = 0.0
                self._speech_ms = self._voiced_run * FRAME_MS
            return None

        self._buf.append(frame)
        if voiced:
            self._silence_ms = 0.0
            self._speech_ms += FRAME_MS
        else:
            self._silence_ms += FRAME_MS
        duration = len(self._buf) * FRAME_MS / 1000
        ended = self._silence_ms >= self.end_silence_ms
        truncated = duration >= self.max_s
        if not (ended or truncated):
            return None
        audio = np.concatenate(self._buf)
        speech_ms = self._speech_ms
        self.reset()
        if speech_ms < self.min_speech_ms:
            return None  # a click or a cough, not an utterance
        return Segment(audio=audio, duration_s=audio.shape[0] / SAMPLE_RATE, truncated=truncated)
