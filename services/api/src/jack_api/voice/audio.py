"""Microphone access through PortAudio (python-sounddevice).

Milestone 2 uses capture only to measure input level (for the orb and the microphone test).
Samples are reduced to a level in the audio callback and immediately discarded; nothing is
buffered, stored or transmitted. Milestone 3 adds VAD, wake word and ASR on top of this.
"""

from __future__ import annotations

import logging
import math
import sys
from array import array
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
BLOCK = 1_600  # 100 ms
FLOOR_DB = -60.0


@dataclass(frozen=True)
class AudioDevice:
    id: str  # stable across reboots: "<host api>:<device name>"
    name: str
    host_api: str
    index: int
    is_default: bool
    channels: int


class LevelStream(Protocol):
    def close(self) -> None: ...


class AudioBackend(Protocol):
    def status(self) -> tuple[bool, str | None]: ...
    def input_devices(self) -> list[AudioDevice]: ...
    def open_level_stream(self, device: AudioDevice | None,
                          on_level: Callable[[float], None]) -> LevelStream: ...


class AudioUnavailable(Exception):
    pass


def level_from_int16(samples: array[int]) -> float:
    """Map RMS of int16 samples to 0..1 on a -60..0 dBFS scale."""
    if not samples:
        return 0.0
    acc = 0
    for v in samples:
        acc += v * v
    rms = math.sqrt(acc / len(samples)) / 32768.0
    if rms <= 0:
        return 0.0
    db = 20 * math.log10(rms)
    return max(0.0, min(1.0, (db - FLOOR_DB) / -FLOOR_DB))


class SoundDeviceBackend:
    """Real PortAudio backend. PortAudio ships inside the sounddevice wheel on Windows/macOS."""

    def __init__(self) -> None:
        self._sd: Any = None
        self._error: str | None = None
        try:
            import sounddevice

            self._sd = sounddevice
        except OSError as exc:  # PortAudio shared library missing (Linux without libportaudio2)
            self._error = f"PortAudio not available: {exc}"

    def status(self) -> tuple[bool, str | None]:
        return (self._sd is not None, self._error)

    def input_devices(self) -> list[AudioDevice]:
        if self._sd is None:
            return []
        sd = self._sd
        try:
            devices = sd.query_devices()
            apis = sd.query_hostapis()
            default_in = sd.default.device[0]
        except Exception as exc:  # noqa: BLE001 - driver errors are reported, not raised
            log.warning("could not enumerate audio devices: %s", exc)
            return []
        out: list[AudioDevice] = []
        for idx, d in enumerate(devices):
            if d["max_input_channels"] < 1:
                continue
            api = apis[d["hostapi"]]["name"]
            out.append(AudioDevice(id=f"{api}:{d['name']}", name=d["name"], host_api=api,
                                   index=idx, is_default=idx == default_in,
                                   channels=d["max_input_channels"]))
        if sys.platform == "win32":
            # WASAPI first: lowest latency, real device names.
            out.sort(key=lambda a: (a.host_api != "Windows WASAPI", a.name))
        return out

    def open_level_stream(self, device: AudioDevice | None,
                          on_level: Callable[[float], None]) -> LevelStream:
        if self._sd is None:
            raise AudioUnavailable(self._error or "audio backend unavailable")
        sd = self._sd

        def callback(indata: Any, _frames: int, _time: Any, _status: Any) -> None:
            samples = array("h")
            samples.frombytes(bytes(indata))
            on_level(level_from_int16(samples))
            # `indata` is reused by PortAudio; we keep no reference to the audio.

        try:
            stream = sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                       blocksize=BLOCK, latency="high",
                                       device=device.index if device else None,
                                       callback=callback)
            stream.start()
        except Exception as exc:  # noqa: BLE001 - PortAudioError and driver errors
            raise AudioUnavailable(f"could not open microphone: {exc}") from exc
        return stream  # type: ignore[no-any-return]
