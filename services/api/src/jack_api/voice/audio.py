"""Microphone access through PortAudio (python-sounddevice).

The backend delivers 16 kHz mono int16 frames of ``FRAME`` samples (32 ms) to a callback.
The callback only copies the frame into a queue; all processing (filtering, level, VAD,
wake word, ASR) happens on the voice worker thread. Audio is never written to disk or sent
off the machine.
"""

from __future__ import annotations

import logging
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
FRAME = 512  # 32 ms; the Silero VAD window at 16 kHz
FLOOR_DB = -60.0

Frames = np.ndarray  # shape (FRAME,), dtype int16


@dataclass(frozen=True)
class AudioDevice:
    id: str  # stable across reboots: "<host api>:<device name>"
    name: str
    host_api: str
    index: int
    is_default: bool
    channels: int


class AudioStream(Protocol):
    def close(self) -> None: ...


class AudioBackend(Protocol):
    def status(self) -> tuple[bool, str | None]: ...
    def input_devices(self) -> list[AudioDevice]: ...
    def open_stream(self, device: AudioDevice | None,
                    on_frame: Callable[[Frames], None]) -> AudioStream: ...


class AudioUnavailable(Exception):
    pass


def level_from_int16(samples: Any) -> float:
    """Map RMS of int16 samples to 0..1 on a -60..0 dBFS scale."""
    a = np.asarray(samples, dtype=np.float64)
    if a.size == 0:
        return 0.0
    rms = math.sqrt(float(np.mean(a * a))) / 32768.0
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

    def open_stream(self, device: AudioDevice | None,
                    on_frame: Callable[[Frames], None]) -> AudioStream:
        if self._sd is None:
            raise AudioUnavailable(self._error or "audio backend unavailable")
        sd = self._sd

        first = [True]

        def callback(indata: Any, _frames: int, _time: Any, status: Any) -> None:
            if first[0]:
                first[0] = False
                log.info("microphone delivering audio")
            if status:
                log.debug("PortAudio input status: %s", status)
            # Copy: PortAudio reuses the buffer after the callback returns.
            on_frame(np.frombuffer(bytes(indata), dtype=np.int16).copy())

        try:
            # latency="high": tolerant of slow drivers; 32 ms frames are still delivered.
            stream = sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                       blocksize=FRAME, latency="high",
                                       device=device.index if device else None,
                                       callback=callback)
            stream.start()
        except Exception as exc:  # noqa: BLE001 - PortAudioError and driver errors
            raise AudioUnavailable(f"could not open microphone: {exc}") from exc
        log.info("microphone opened: %s (latency %.0f ms)",
                 device.id if device else "system default", 1000 * float(stream.latency))
        return stream  # type: ignore[no-any-return]
