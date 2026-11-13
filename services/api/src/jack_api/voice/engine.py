"""Voice engine (Milestone 3).

Pipeline (Section 4):
    microphone → high-pass noise filter → VAD → wake word → speech recognition →
    command → task → spoken response

Everything runs locally. Audio frames travel from the PortAudio callback through an
in-memory queue to one worker thread; they are never written to disk or sent anywhere.
Only transcripts (text) are kept, in the conversation history, subject to retention and
privacy mode.

States
    disabled   — muted or privacy mode; the microphone cannot open
    idle       — microphone closed (wake word off or unavailable)
    standby    — microphone open, listening only for "Jack" / "Hey Jack"
    listening  — capturing a command (push-to-talk, or after the wake word)
    processing — recognising speech
    speaking   — playing a reply (interruptible; push-to-talk barges in)
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from jack_api.audit import AuditLog
from jack_api.settings_store import SettingsStore
from jack_api.voice.asr import MODELS, WAKE_MODEL, Recognizer
from jack_api.voice.audio import (
    AudioBackend,
    AudioDevice,
    AudioStream,
    AudioUnavailable,
    level_from_int16,
)
from jack_api.voice.dsp import FRAME_MS, HighPass, Segment, Segmenter
from jack_api.voice.history import VoiceHistory
from jack_api.voice.tts import TtsBackend
from jack_api.voice.vad import Vad
from jack_api.voice.wakeword import KeywordAsrDetector, WakeDetector, split_wake

log = logging.getLogger(__name__)

SETTINGS_KEY = "voice"
LEVEL_INTERVAL_S = 1 / 15  # throttle level events to 15 Hz
NO_AUDIO_TIMEOUT_S = 4.0  # a microphone that opens but delivers nothing is reported, not hidden
COMMAND_WAIT_S = 6.0  # after "Jack", how long to wait for the command to start
FOLLOWUP_WAIT_S = 8.0  # after JACK asks a question, how long to wait for the answer to start
ECHO_GUARD_S = 0.3  # ignore audio this long after JACK stops speaking
PTT_TAIL_S = 0.25  # keep capturing briefly after release: people let go as they finish
QUEUE_FRAMES = 400  # ~13 s of 32 ms frames
WAKE_SEGMENT_MAX_S = 12.0

Publisher = Callable[[str, Any], None]
Notifier = Callable[[str, str, str | None], object]  # (kind, title, body): warning notification
@dataclass
class CommandResult:
    """What the command handler (requirement discovery) made of a transcript."""
    task_id: str | None
    reply: str
    listen: bool = False  # JACK asked a question: keep listening for the answer


CommandHandler = Callable[[str], CommandResult]

ASR_MODEL_CHOICES = Literal["tiny.en", "base.en", "small.en"]


class VoiceState(StrEnum):
    DISABLED = "disabled"
    IDLE = "idle"
    STANDBY = "standby"
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
    asr_model: ASR_MODEL_CHOICES = "small.en"
    end_of_speech_ms: int = Field(default=800, ge=300, le=3000)
    tts_enabled: bool = True
    tts_voice_id: str | None = None
    tts_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    keep_history: bool = True
    history_retention_days: int = Field(default=30, ge=1, le=365)


class VoiceSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wake_word_enabled: bool | None = None
    wake_word_sensitivity: float | None = Field(default=None, ge=0.1, le=0.9)
    input_device_id: str | None = None
    muted: bool | None = None
    privacy_mode: bool | None = None
    max_listen_s: int | None = Field(default=None, ge=5, le=120)
    asr_model: ASR_MODEL_CHOICES | None = None
    end_of_speech_ms: int | None = Field(default=None, ge=300, le=3000)
    tts_enabled: bool | None = None
    tts_voice_id: str | None = None
    tts_rate: float | None = Field(default=None, ge=0.5, le=2.0)
    keep_history: bool | None = None
    history_retention_days: int | None = Field(default=None, ge=1, le=365)


class VoiceBlocked(Exception):
    """Capture refused (muted, privacy mode, no device, backend error)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Capabilities:
    capture: bool
    capture_detail: str | None
    wake_word: bool
    wake_word_detail: str | None
    wake_word_engine: str
    speech_recognition: bool
    speech_recognition_detail: str | None
    speech_synthesis: bool
    speech_synthesis_detail: str | None
    speech_synthesis_engine: str


@dataclass
class Utterance:
    trigger: str  # ptt | wake
    captured_ms: int
    transcribed: bool
    transcript: str | None
    reply: str
    stopped_by: str
    task_id: str | None


@dataclass
class PttStopped:
    captured_ms: int
    stopped_by: str
    processing: bool


Mode = Literal["none", "ptt", "ptt_closing", "wake_command", "followup"]


class VoiceEngine:
    def __init__(self, backend: AudioBackend, store: SettingsStore, audit: AuditLog,
                 publish: Publisher, *, recognizer: Recognizer, tts: TtsBackend,
                 vad_factory: Callable[[], Vad], history: VoiceHistory | None = None,
                 on_command: CommandHandler | None = None, notify: Notifier | None = None,
                 wake_detector: WakeDetector | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._backend = backend
        self._store = store
        self._audit = audit
        self._publish = publish
        self._asr = recognizer
        self._tts = tts
        self._vad_factory = vad_factory
        self._vad: Vad | None = None
        self._history = history
        self._on_command = on_command
        self._notify = notify
        self._wake = wake_detector or KeywordAsrDetector(recognizer)
        self._clock = clock
        self.no_audio_timeout_s = NO_AUDIO_TIMEOUT_S
        self.command_wait_s = COMMAND_WAIT_S
        self.followup_wait_s = FOLLOWUP_WAIT_S

        self._lock = threading.RLock()
        self._settings = store.get(SETTINGS_KEY, VoiceSettings)
        self._state = VoiceState.IDLE
        self._mode: Mode = "none"
        self._stream: AudioStream | None = None
        self._stream_opened_at = 0.0
        self._frames_seen = 0
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=QUEUE_FRAMES)
        self._hp = HighPass()
        self._seg = Segmenter()
        self._ptt_buf: list[np.ndarray] = []
        self._ptt_voiced = 0
        self._mode_started = 0.0
        self._source = ""
        self._last_level_at = 0.0
        self._ignore_until = 0.0
        self._tts_cancel = threading.Event()
        self._stop = threading.Event()
        self._jobs: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self.last_result: Utterance | None = None
        self._worker = threading.Thread(target=self._run, name="jack-voice", daemon=True)
        self._worker.start()
        with self._lock:
            self._settle()

    # ================================================================== queries
    @property
    def settings(self) -> VoiceSettings:
        return self._settings

    @property
    def state(self) -> VoiceState:
        return self._state

    def capabilities(self) -> Capabilities:
        ok, detail = self._backend.status()
        if ok and not self._backend.input_devices():
            ok, detail = False, "No microphone found"
        wake_ok, wake_detail = self._wake.available()
        asr_model = self._settings.asr_model
        asr_ok = self._asr.available(asr_model)
        tts_ok, tts_detail = self._tts.available()
        return Capabilities(
            capture=ok, capture_detail=detail,
            wake_word=wake_ok and ok, wake_word_detail=wake_detail if ok else detail,
            wake_word_engine=self._wake.engine,
            speech_recognition=asr_ok,
            speech_recognition_detail=None if asr_ok else
            f"Download the {asr_model} speech model on the Voice page",
            speech_synthesis=tts_ok, speech_synthesis_detail=tts_detail,
            speech_synthesis_engine=self._tts.engine,
        )

    def devices(self) -> list[AudioDevice]:
        return self._backend.input_devices()

    def voices(self) -> list[dict[str, Any]]:
        return [asdict(v) for v in self._tts.voices()]

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
            "settings": self._settings.model_dump(mode="json"),
            "capabilities": asdict(self.capabilities()),
            "listening_since_s": (round(self._clock() - self._mode_started, 1)
                                  if self._state is VoiceState.LISTENING else None),
        }

    # ================================================================== settings
    def update_settings(self, patch: VoiceSettingsPatch) -> VoiceSettings:
        changes = patch.model_dump(exclude_unset=True)
        with self._lock:
            new = VoiceSettings.model_validate(self._settings.model_copy(update=changes)
                                               .model_dump())
            if changes.get("input_device_id") and self._find_device(new.input_device_id) is None:
                raise VoiceBlocked("unknown_device", "Selected microphone is not available")
            if changes.get("tts_voice_id") and new.tts_voice_id not in {
                    v["id"] for v in self.voices()}:
                raise VoiceBlocked("unknown_voice", "Selected voice is not available")
            self._store.put(SETTINGS_KEY, new)
            device_changed = new.input_device_id != self._settings.input_device_id
            self._settings = new
            if new.muted or new.privacy_mode:
                self._tts_cancel.set()
                if self._state is VoiceState.LISTENING:
                    self._mode = "none"
                    self._ptt_buf = []
            if device_changed:
                self._close_stream()
            self._settle()
        self._audit.record("voice.settings.update", outcome="allowed", actor_type="user",
                           details=dict(changes.items()))
        self._publish("voice.settings", new.model_dump(mode="json"))
        return new

    # ================================================================== push-to-talk
    def start_ptt(self, source: str) -> VoiceState:
        with self._lock:
            if self._mode == "ptt":
                return self._state
            self._check_capture_allowed()
            self._tts_cancel.set()  # barge-in: stop JACK talking
            self._open_stream_if_needed(source=source)
            self._begin_mode("ptt", source)
        self._audit.record("voice.capture.start", outcome="allowed", actor_type="user",
                           details={"source": source, "device": self._device_label()})
        return VoiceState.LISTENING

    def stop_ptt(self, reason: str = "released") -> PttStopped | None:
        with self._lock:
            return self._stop_ptt_locked(reason)

    def _stop_ptt_locked(self, reason: str) -> PttStopped | None:
        if self._mode != "ptt":
            return None
        released_at = self._clock()
        captured_ms = int((released_at - self._mode_started) * 1000)
        # Frames already captured may still be queued; the worker collects them (plus a
        # short tail) before recognising, so the last word is not clipped.
        self._mode = "ptt_closing"
        self._audit.record("voice.capture.stop", outcome="info", actor_type="user",
                           details={"captured_ms": captured_ms, "stopped_by": reason})
        self._jobs_put(("ptt", released_at, captured_ms, reason))
        return PttStopped(captured_ms=captured_ms, stopped_by=reason, processing=True)

    def _collect_ptt_tail(self, released_at: float) -> tuple[np.ndarray, int]:
        tail_until = released_at + PTT_TAIL_S
        while True:
            try:
                frame = self._queue.get(timeout=0.02)
            except queue.Empty:
                if self._clock() >= tail_until or self._stream is None:
                    break
                continue
            with self._lock:
                if self._mode != "ptt_closing":
                    break
                self._frames_seen += 1
                f = self._hp(frame)
                if self._vad is None:
                    self._vad = self._vad_factory()
                if self._vad.prob(f) >= 0.5:
                    self._ptt_voiced += 1
                self._ptt_buf.append(f)
            if self._clock() >= tail_until and self._queue.empty():
                break
        with self._lock:
            audio = np.concatenate(self._ptt_buf) if self._ptt_buf else np.zeros(0, np.float32)
            voiced = self._ptt_voiced
            self._ptt_buf = []
            if self._mode == "ptt_closing":
                self._mode = "none"
            self._set_state(VoiceState.PROCESSING)
        return audio, voiced

    def speak(self, text: str) -> None:
        """Say something (used by the Voice page's voice test)."""
        self._jobs_put(("say", text))

    def stop_speaking(self) -> bool:
        if self._state is VoiceState.SPEAKING:
            self._tts_cancel.set()
            return True
        return False

    def shutdown(self) -> None:
        self._stop.set()
        self._tts_cancel.set()
        with self._lock:
            self._mode = "none"
            self._close_stream()
        self._worker.join(timeout=3)

    # ================================================================== internals: control
    def _jobs_put(self, job: tuple[Any, ...]) -> None:
        self._jobs.put(job)

    def _check_capture_allowed(self) -> None:
        if self._settings.privacy_mode:
            raise VoiceBlocked("privacy_mode", "Privacy mode is on; the microphone is off")
        if self._settings.muted:
            raise VoiceBlocked("muted", "The microphone is muted")
        if self._settings.input_device_id and self._find_device(
                self._settings.input_device_id) is None:
            raise VoiceBlocked("unknown_device", "Selected microphone is not available")

    def _wake_active(self) -> bool:
        s = self._settings
        return (s.wake_word_enabled and not s.muted and not s.privacy_mode
                and self.capabilities().wake_word)

    def _resting_state(self) -> VoiceState:
        s = self._settings
        if s.muted or s.privacy_mode:
            return VoiceState.DISABLED
        return VoiceState.STANDBY if self._wake_active() else VoiceState.IDLE

    def _settle(self, force: bool = False) -> None:
        """Bring stream and state in line with settings when not mid-interaction."""
        busy = self._state in (VoiceState.PROCESSING, VoiceState.SPEAKING) and not force
        if busy or self._mode != "none":
            if self._settings.muted or self._settings.privacy_mode:
                self._mode = "none"
                self._close_stream()
            return
        if self._wake_active():
            try:
                self._open_stream_if_needed(source="wake")
            except VoiceBlocked as exc:
                self._report_error(exc.code, str(exc))
                self._set_state(VoiceState.IDLE)
                return
        else:
            self._close_stream()
        self._set_state(self._resting_state())

    def _begin_mode(self, mode: Mode, source: str) -> None:
        self._mode = mode
        self._source = source
        self._mode_started = self._clock()
        self._ptt_buf = []
        self._ptt_voiced = 0
        self._seg = Segmenter(end_silence_ms=self._settings.end_of_speech_ms,
                              max_s=float(self._settings.max_listen_s))
        self._set_state(VoiceState.LISTENING)

    def _open_stream_if_needed(self, *, source: str) -> None:
        if self._stream is not None:
            return
        device = None
        if self._settings.input_device_id:
            device = self._find_device(self._settings.input_device_id)
            if device is None:
                raise VoiceBlocked("unknown_device", "Selected microphone is not available")
        try:
            self._stream = self._backend.open_stream(device, self._on_frame)
        except AudioUnavailable as exc:
            self._audit.record("voice.capture.start", outcome="error", actor_type="user",
                               details={"source": source, "error": str(exc)})
            raise VoiceBlocked("audio_unavailable", str(exc)) from exc
        self._stream_opened_at = self._clock()
        self._frames_seen = 0
        self._hp.reset()
        self._vad = None  # recreated lazily on the worker thread
        self._seg = Segmenter(end_silence_ms=500, max_s=WAKE_SEGMENT_MAX_S)
        if source == "wake":
            self._audit.record("voice.standby.start", outcome="info", actor_type="system",
                               details={"device": self._device_label()})

    def _close_stream(self) -> None:
        if self._stream is None:
            return
        try:
            self._stream.close()
        finally:
            self._stream = None
            self._drain()

    def _drain(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass

    def _set_state(self, state: VoiceState) -> None:
        if state is self._state:
            return
        self._state = state
        self._publish("voice.state", {"state": state.value})

    def _find_device(self, device_id: str | None) -> AudioDevice | None:
        return next((d for d in self._backend.input_devices() if d.id == device_id), None)

    def _device_label(self) -> str:
        d = self._find_device(self._settings.input_device_id)
        return d.id if d else "system default"

    def _report_error(self, code: str, message: str, notify_title: str | None = None) -> None:
        self._publish("voice.error", {"code": code, "message": message})
        if notify_title and self._notify:
            self._notify(f"voice.{code}", notify_title, message)

    # ================================================================== internals: audio
    def _on_frame(self, frame: np.ndarray) -> None:
        """PortAudio callback thread: hand off only."""
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            pass  # worker busy (processing/speaking); dropping is correct (half-duplex)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job: tuple[Any, ...] | None = self._jobs.get_nowait()
            except queue.Empty:
                job = None
            if job is not None:
                try:
                    self._handle_job(job)
                except Exception:  # noqa: BLE001 - the voice loop must survive anything
                    log.exception("voice job failed")
                    with self._lock:
                        self._mode = "none"
                        self._settle(force=True)
                continue
            try:
                frame = self._queue.get(timeout=0.05)
            except queue.Empty:
                frame = None
            try:
                with self._lock:
                    if frame is not None:
                        self._frames_seen += 1
                        self._process_frame(frame)
                    self._tick()
            except Exception:  # noqa: BLE001
                log.exception("voice frame processing failed")

    def _process_frame(self, raw: np.ndarray) -> None:
        if self._state in (VoiceState.PROCESSING, VoiceState.SPEAKING):
            return  # half-duplex: don't listen to ourselves
        if self._clock() < self._ignore_until:
            return
        f = self._hp(raw)
        if self._vad is None:
            self._vad = self._vad_factory()
        prob = self._vad.prob(f)
        if self._mode in ("ptt", "ptt_closing"):
            self._ptt_buf.append(f)
            if prob >= 0.5:
                self._ptt_voiced += 1
            self._emit_level(raw)
        elif self._mode in ("wake_command", "followup"):
            self._emit_level(raw)
            seg = self._seg.push(f, prob)
            if seg is not None:
                trigger = "followup" if self._mode == "followup" else "wake"
                self._mode = "none"
                self._set_state(VoiceState.PROCESSING)
                self._jobs_put(("command", seg, trigger))
        elif self._state is VoiceState.STANDBY:
            seg = self._seg.push(f, prob)
            if seg is not None:
                self._jobs_put(("wake", seg))

    def _emit_level(self, raw: np.ndarray) -> None:
        now = self._clock()
        if now - self._last_level_at < LEVEL_INTERVAL_S:
            return
        self._last_level_at = now
        self._publish("voice.level", {"level": round(level_from_int16(raw), 3)})

    def _tick(self) -> None:
        now = self._clock()
        if self._stream is not None and self._frames_seen == 0 and \
                now - self._stream_opened_at > self.no_audio_timeout_s:
            name = self._device_label()
            msg = (f"No audio is arriving from the microphone ({name}). Check that it is "
                   "connected, not in use by another app, and that microphone access is "
                   "allowed in Windows privacy settings.")
            was_ptt = self._mode == "ptt"
            self._mode = "none"
            self._ptt_buf = []
            self._close_stream()
            if was_ptt:
                self.last_result = Utterance("ptt", int((now - self._mode_started) * 1000),
                                             False, None, "", "no_audio", None)
                self._audit.record("voice.capture.stop", outcome="error", actor_type="user",
                                   details={"stopped_by": "no_audio"})
            self._set_state(VoiceState.IDLE)
            self._report_error("no_audio", msg, "No audio from microphone")
            return
        if self._mode == "ptt" and now - self._mode_started >= self._settings.max_listen_s:
            self._stop_ptt_locked("max_duration")
        elif self._mode == "wake_command" and not self._seg.in_speech and \
                now - self._mode_started >= self.command_wait_s:
            self._mode = "none"
            self._jobs_put(("reply_only", "I didn't hear a command.", "wake"))
        elif self._mode == "followup" and not self._seg.in_speech and \
                now - self._mode_started >= self.followup_wait_s:
            # No answer: stop listening quietly. The question stays open; the user can answer
            # later with push-to-talk, the wake word, or in the Command Centre.
            self._mode = "none"
            self._audit.record("voice.followup.end", outcome="info", actor_type="system",
                               details={"answered": False})
            self._jobs_put(("end",))

    # ================================================================== internals: jobs
    def _handle_job(self, job: tuple[Any, ...]) -> None:
        kind = job[0]
        if kind == "ptt":
            _, released_at, captured_ms, reason = job
            audio, voiced = self._collect_ptt_tail(released_at)
            self._handle_ptt(audio, voiced, captured_ms, reason)
        elif kind == "wake":
            self._handle_wake(job[1])
        elif kind == "command":
            seg: Segment = job[1]
            trigger = job[2] if len(job) > 2 else "wake"
            self._handle_command_audio(seg.audio, trigger, int(seg.duration_s * 1000),
                                       "end_of_speech" if not seg.truncated else "max_duration",
                                       strip_wake=True)
        elif kind == "reply_only":
            self._reply(job[1])
            self._finish()
        elif kind == "say":
            self._reply(job[1])
            self._finish()
        elif kind == "end":
            self._finish()

    def _handle_ptt(self, audio: np.ndarray, voiced: int, captured_ms: int, reason: str) -> None:
        if voiced * FRAME_MS < 200:
            self._complete(Utterance("ptt", captured_ms, False, None,
                                     "I didn't hear anything.", reason, None), speak=True)
            return
        self._handle_command_audio(audio, "ptt", captured_ms, reason, strip_wake=True)

    def _handle_wake(self, seg: Segment) -> None:
        sens = self._settings.wake_word_sensitivity
        decision = self._wake.check(seg.audio, sens)
        if not decision.detected:
            log.debug("wake rejected (%s): %r", decision.reason, decision.transcript)
            return
        self._audit.record("voice.wake", outcome="info", actor_type="user",
                           details={"engine": self._wake.engine})
        self._publish("voice.wake", {"transcript": decision.transcript})
        if len(decision.remainder.split()) >= 2:
            # "Jack, build a website" in one breath: re-transcribe the whole utterance with
            # the (more accurate) command model.
            with self._lock:
                self._set_state(VoiceState.PROCESSING)
            self._handle_command_audio(seg.audio, "wake", int(seg.duration_s * 1000),
                                       "end_of_speech", strip_wake=True)
            return
        self._reply("Yes, I'm listening.")
        with self._lock:
            if self._settings.muted or self._settings.privacy_mode:
                self._finish()
                return
            self._ignore_until = self._clock() + ECHO_GUARD_S
            self._begin_mode("wake_command", "wake")

    def _handle_command_audio(self, audio: np.ndarray, trigger: str, captured_ms: int,
                              reason: str, *, strip_wake: bool) -> None:
        model = self._settings.asr_model
        if not self._asr.available(model):
            self._complete(Utterance(trigger, captured_ms, False, None,
                                     "I can't understand speech yet. Download a speech model "
                                     "on the Voice page.", reason, None), speak=True)
            return
        with self._lock:
            self._set_state(VoiceState.PROCESSING)
        t = self._asr.transcribe(audio, model)
        text = t.text.strip()
        if strip_wake:
            matched, rest = split_wake(text, self._settings.wake_word_sensitivity)
            if matched:
                text = rest
        text = text.strip(" ,.")
        if not text:
            self._complete(Utterance(trigger, captured_ms, True, "",
                                     "Sorry, I didn't catch that.", reason, None), speak=True)
            return
        task_id: str | None = None
        listen = False
        if self._on_command is not None:
            try:
                result = self._on_command(text)
            except Exception:  # noqa: BLE001 - a handler failure must not break the voice loop
                log.exception("command handler failed")
                result = CommandResult(None, "Sorry, something went wrong handling that. "
                                             "It's been logged.")
            task_id, reply, listen = result.task_id, result.reply, result.listen
        else:
            reply = "Got it."
        self._complete(Utterance(trigger, captured_ms, True, text, reply, reason, task_id),
                       speak=True, follow_up=listen)

    def _complete(self, u: Utterance, *, speak: bool, follow_up: bool = False) -> None:
        self.last_result = u
        self._publish("voice.utterance", asdict(u))
        if self._settings.keep_history and not self._settings.privacy_mode and \
                self._history is not None and (u.transcript or u.reply):
            sid = self._history.start(u.trigger)
            if u.transcript:
                self._history.add_turn(sid, "user", u.transcript)
            self._history.add_turn(sid, "jack", u.reply)
            self._history.end(sid, u.task_id)
        if speak:
            self._reply(u.reply)
        if follow_up and self._start_followup():
            return
        self._finish()

    def _start_followup(self) -> bool:
        """After a question, listen for the answer without the wake word (Section 4: one
        question at a time). Never in privacy mode or when muted."""
        with self._lock:
            s = self._settings
            if s.muted or s.privacy_mode or self._mode == "ptt" or \
                    not self.capabilities().capture:
                return False
            try:
                self._open_stream_if_needed(source="followup")
            except VoiceBlocked as exc:
                self._report_error(exc.code, str(exc))
                return False
            self._drain()
            if self._vad is not None:
                self._vad.reset()
            self._ignore_until = self._clock() + ECHO_GUARD_S
            self._begin_mode("followup", "followup")
            self._audit.record("voice.followup.start", outcome="info", actor_type="system",
                               details={"wait_s": self.followup_wait_s})
            self._publish("voice.followup", {"wait_s": self.followup_wait_s})
            return True

    def _reply(self, text: str) -> None:
        self._publish("voice.reply", {"text": text})
        s = self._settings
        if not s.tts_enabled or s.muted or s.privacy_mode or not self._tts.available()[0]:
            return
        with self._lock:
            if self._mode == "ptt":
                return  # user already pressed push-to-talk again
            self._tts_cancel.clear()
            self._set_state(VoiceState.SPEAKING)
        try:
            self._tts.speak(text, s.tts_voice_id, s.tts_rate, self._tts_cancel)
        except Exception as exc:  # noqa: BLE001 - playback failure must not break the loop
            log.warning("text-to-speech failed: %s", exc)
            self._report_error("tts_failed", f"Couldn't play JACK's spoken reply: {exc}")
        finally:
            self._ignore_until = self._clock() + ECHO_GUARD_S

    def _finish(self) -> None:
        with self._lock:
            if self._mode == "ptt":
                self._set_state(VoiceState.LISTENING)  # barge-in started a new capture
                return
            self._mode = "none"
            self._drain()
            self._seg = Segmenter(end_silence_ms=500, max_s=WAKE_SEGMENT_MAX_S)
            if self._vad is not None:
                self._vad.reset()
            self._settle(force=True)


__all__ = ["MODELS", "WAKE_MODEL", "VoiceEngine", "VoiceSettings", "VoiceSettingsPatch",
           "VoiceBlocked", "VoiceState"]
