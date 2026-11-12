"""Voice engine (Milestone 2 scope).

Implements the voice *interface*: settings, microphone selection, mute/privacy enforcement,
push-to-talk capture with a live input level, and the listening/processing/speaking state
machine the UI renders. Wake-word detection, speech recognition and speech synthesis are
reported as unavailable until Milestone 3 — the engine never pretends to transcribe.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jack_api.audit import AuditLog
from jack_api.settings_store import SettingsStore
from jack_api.voice.audio import AudioBackend, AudioDevice, AudioUnavailable, LevelStream

SETTINGS_KEY = "voice"
LEVEL_INTERVAL_S = 1 / 15  # throttle level events to 15 Hz
NO_AUDIO_TIMEOUT_S = 2.0  # a microphone that opens but delivers nothing is reported, not hidden
M3_NOTE = "Speech recognition arrives in Milestone 3; the captured audio was discarded."

Publisher = Callable[[str, Any], None]
Notifier = Callable[[str, str, str | None], object]  # (kind, title, body): warning notification


class VoiceState(StrEnum):
    DISABLED = "disabled"  # muted or privacy mode
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"


class VoiceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wake_word_enabled: bool = False
    wake_word_sensitivity: float = Field(default=0.5, ge=0.1, le=0.9)
    input_device_id: str | None = None
    muted: bool = False
    privacy_mode: bool = False
    max_listen_s: int = Field(default=30, ge=5, le=120)


class VoiceSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wake_word_enabled: bool | None = None
    wake_word_sensitivity: float | None = Field(default=None, ge=0.1, le=0.9)
    input_device_id: str | None = None
    muted: bool | None = None
    privacy_mode: bool | None = None
    max_listen_s: int | None = Field(default=None, ge=5, le=120)


class VoiceBlocked(Exception):
    """Capture refused (muted, privacy mode, no device, backend error)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Capabilities:
    capture: bool
    capture_detail: str | None
    wake_word: bool = False
    speech_recognition: bool = False
    speech_synthesis: bool = False
    pending_milestone: int = 3


@dataclass
class PttResult:
    captured_ms: int
    transcribed: bool
    transcript: str | None
    detail: str
    stopped_by: str


class VoiceEngine:
    def __init__(self, backend: AudioBackend, store: SettingsStore, audit: AuditLog,
                 publish: Publisher, clock: Callable[[], float] = time.monotonic,
                 notify: Notifier | None = None) -> None:
        self._backend = backend
        self._store = store
        self._audit = audit
        self._publish = publish
        self._clock = clock
        self._notify = notify
        self.no_audio_timeout_s = NO_AUDIO_TIMEOUT_S
        self._levels_seen = 0
        self._watchdog: threading.Timer | None = None
        self._lock = threading.RLock()
        self._settings = store.get(SETTINGS_KEY, VoiceSettings)
        self._state = self._resting_state()
        self._stream: LevelStream | None = None
        self._started_at = 0.0
        self._source = ""
        self._timer: threading.Timer | None = None
        self._last_level_at = 0.0
        self.last_result: PttResult | None = None

    # ------------------------------------------------------------------ queries
    @property
    def settings(self) -> VoiceSettings:
        return self._settings

    @property
    def state(self) -> VoiceState:
        return self._state

    def capabilities(self) -> Capabilities:
        ok, detail = self._backend.status()
        if ok and not self._backend.input_devices():
            return Capabilities(capture=False, capture_detail="No microphone found")
        return Capabilities(capture=ok, capture_detail=detail)

    def devices(self) -> list[AudioDevice]:
        return self._backend.input_devices()

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
            "settings": self._settings.model_dump(mode="json"),
            "capabilities": asdict(self.capabilities()),
            "listening_since_s": (round(self._clock() - self._started_at, 1)
                                  if self._state is VoiceState.LISTENING else None),
        }

    # ------------------------------------------------------------------ settings
    def update_settings(self, patch: VoiceSettingsPatch) -> VoiceSettings:
        changes = patch.model_dump(exclude_unset=True)
        with self._lock:
            new = self._settings.model_copy(update=changes)
            VoiceSettings.model_validate(new.model_dump())  # re-validate merged result
            if "input_device_id" in changes and new.input_device_id is not None and \
                    self._find_device(new.input_device_id) is None:
                raise VoiceBlocked("unknown_device", "Selected microphone is not available")
            self._store.put(SETTINGS_KEY, new)
            self._settings = new
            blocking = new.muted or new.privacy_mode
            if blocking and self._state is VoiceState.LISTENING:
                self._stop_locked("muted")
            self._set_state(self._resting_state() if self._state in
                            (VoiceState.IDLE, VoiceState.DISABLED) else self._state)
        self._audit.record("voice.settings.update", outcome="allowed", actor_type="user",
                           details={k: v for k, v in changes.items()})
        self._publish("voice.settings", new.model_dump(mode="json"))
        return new

    # ------------------------------------------------------------------ push-to-talk
    def start_ptt(self, source: str) -> VoiceState:
        with self._lock:
            if self._state is VoiceState.LISTENING:
                return self._state
            if self._settings.privacy_mode:
                raise VoiceBlocked("privacy_mode", "Privacy mode is on; the microphone is off")
            if self._settings.muted:
                raise VoiceBlocked("muted", "The microphone is muted")
            device = None
            if self._settings.input_device_id:
                device = self._find_device(self._settings.input_device_id)
                if device is None:
                    raise VoiceBlocked("unknown_device", "Selected microphone is not available")
            try:
                self._stream = self._backend.open_level_stream(device, self._on_level)
            except AudioUnavailable as exc:
                self._audit.record("voice.capture.start", outcome="error", actor_type="user",
                                   details={"source": source, "error": str(exc)})
                raise VoiceBlocked("audio_unavailable", str(exc)) from exc
            self._started_at = self._clock()
            self._source = source
            self._levels_seen = 0
            self._timer = threading.Timer(self._settings.max_listen_s, self._auto_stop)
            self._timer.daemon = True
            self._timer.start()
            self._watchdog = threading.Timer(self.no_audio_timeout_s, self._check_audio,
                                             args=(device.name if device else "default",))
            self._watchdog.daemon = True
            self._watchdog.start()
            self._set_state(VoiceState.LISTENING)
        self._audit.record("voice.capture.start", outcome="allowed", actor_type="user",
                           details={"source": source,
                                    "device": device.id if device else "system default"})
        return VoiceState.LISTENING

    def stop_ptt(self, reason: str = "released") -> PttResult | None:
        with self._lock:
            if self._state is not VoiceState.LISTENING:
                return None
            result = self._stop_locked(reason)
        return result

    def _auto_stop(self) -> None:
        self.stop_ptt("max_duration")

    def _check_audio(self, device_name: str) -> None:
        with self._lock:
            if self._state is not VoiceState.LISTENING or self._levels_seen > 0:
                return
            self._stop_locked("no_audio")
        message = (f"No audio is arriving from the microphone ({device_name}). Check that it is "
                   "connected, not in use by another app, and that microphone access is allowed "
                   "in Windows privacy settings.")
        self._publish("voice.error", {"code": "no_audio", "message": message})
        if self._notify:
            self._notify("voice.no_audio", "No audio from microphone", message)

    def _stop_locked(self, reason: str) -> PttResult:
        for t in (self._timer, self._watchdog):
            if t is not None and t is not threading.current_thread():
                t.cancel()
        self._timer = self._watchdog = None
        if self._stream is not None:
            try:
                self._stream.close()
            finally:
                self._stream = None
        captured_ms = int((self._clock() - self._started_at) * 1000)
        result = PttResult(captured_ms=captured_ms, transcribed=False, transcript=None,
                           detail=M3_NOTE, stopped_by=reason)
        self.last_result = result
        self._set_state(self._resting_state())
        self._audit.record("voice.capture.stop", outcome="info", actor_type="user",
                           details={"captured_ms": captured_ms, "stopped_by": reason})
        self._publish("voice.utterance", asdict(result))
        return result

    def shutdown(self) -> None:
        self.stop_ptt("shutdown")

    # ------------------------------------------------------------------ internals
    def _find_device(self, device_id: str) -> AudioDevice | None:
        return next((d for d in self._backend.input_devices() if d.id == device_id), None)

    def _resting_state(self) -> VoiceState:
        s = self._settings
        return VoiceState.DISABLED if (s.muted or s.privacy_mode) else VoiceState.IDLE

    def _set_state(self, state: VoiceState) -> None:
        if state is self._state:
            return
        self._state = state
        self._publish("voice.state", {"state": state.value})

    def _on_level(self, level: float) -> None:
        self._levels_seen += 1
        now = self._clock()
        if now - self._last_level_at < LEVEL_INTERVAL_S:
            return
        self._last_level_at = now
        self._publish("voice.level", {"level": round(level, 3)})
