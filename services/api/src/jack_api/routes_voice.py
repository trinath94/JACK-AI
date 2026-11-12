"""Voice routes (Milestones 2–3): status, devices, settings, push-to-talk, speech models,
text-to-speech and conversation history."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from jack_api.voice.asr import MODELS
from jack_api.voice.engine import VoiceSettings, VoiceSettingsPatch

if TYPE_CHECKING:
    from jack_api.app import Services

router = APIRouter(prefix="/v1/voice")


def _svc(request: Request) -> Services:
    svc: Services = request.app.state.svc
    return svc


class AudioDeviceOut(BaseModel):
    id: str
    name: str
    host_api: str
    is_default: bool
    channels: int


class VoiceCapabilities(BaseModel):
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


class VoiceStatus(BaseModel):
    state: Literal["disabled", "idle", "standby", "listening", "processing", "speaking"]
    settings: VoiceSettings
    capabilities: VoiceCapabilities
    listening_since_s: float | None


class PttStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["ui", "hotkey", "tray"] = "ui"


class PttStoppedOut(BaseModel):
    captured_ms: int
    stopped_by: str
    processing: bool


class UtteranceOut(BaseModel):
    """Payload of the ``voice.utterance`` WebSocket event."""

    trigger: Literal["ptt", "wake"]
    captured_ms: int
    transcribed: bool
    transcript: str | None
    reply: str
    stopped_by: str
    task_id: str | None


class TtsVoiceOut(BaseModel):
    id: str
    name: str
    language: str | None


class SpeakBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)


class SpeechModelOut(BaseModel):
    name: str
    size_mb: int
    purpose: str
    status: Literal["not_downloaded", "downloading", "ready", "error"]
    downloaded_mb: float
    error: str | None


class TurnOut(BaseModel):
    role: Literal["user", "jack"]
    text: str
    created_at: str


class SessionOut(BaseModel):
    id: str
    trigger: str
    started_at: str
    ended_at: str | None
    task_id: str | None
    turns: list[TurnOut]


class HistoryOut(BaseModel):
    items: list[SessionOut]
    total: int


@router.get("/status", response_model=VoiceStatus)
def voice_status(request: Request) -> Any:
    return _svc(request).voice.snapshot()


@router.get("/devices", response_model=list[AudioDeviceOut])
def voice_devices(request: Request) -> Any:
    return [asdict(d) for d in _svc(request).voice.devices()]


@router.get("/voices", response_model=list[TtsVoiceOut])
def tts_voices(request: Request) -> Any:
    return _svc(request).voice.voices()


@router.patch("/settings", response_model=VoiceSettings)
def voice_settings(body: VoiceSettingsPatch, request: Request) -> Any:
    return _svc(request).voice.update_settings(body)


@router.post("/ptt/start", response_model=VoiceStatus)
def ptt_start(body: PttStart, request: Request) -> Any:
    voice = _svc(request).voice
    voice.start_ptt(body.source)
    return voice.snapshot()


@router.post("/ptt/stop", response_model=PttStoppedOut | None)
def ptt_stop(request: Request) -> Any:
    """Closes the microphone. Recognition continues in the background; the result arrives
    as a ``voice.utterance`` event."""
    result = _svc(request).voice.stop_ptt("released")
    return asdict(result) if result else None


@router.post("/speak", status_code=202)
def speak(body: SpeakBody, request: Request) -> dict[str, bool]:
    _svc(request).voice.speak(body.text)
    return {"queued": True}


@router.post("/stop-speaking")
def stop_speaking(request: Request) -> dict[str, bool]:
    return {"stopped": _svc(request).voice.stop_speaking()}


@router.get("/models", response_model=list[SpeechModelOut])
def models(request: Request) -> Any:
    return _svc(request).models.snapshot()


@router.post("/models/{name}/download", status_code=202)
def model_download(name: str, request: Request) -> dict[str, bool]:
    if name not in MODELS:
        raise HTTPException(404, "Unknown speech model")
    svc = _svc(request)
    started = svc.models.download(name)
    svc.audit.record("voice.model.download", outcome="allowed", actor_type="user",
                     target=name, details={"started": started})
    return {"started": started}


@router.delete("/models/{name}", status_code=204)
def model_delete(name: str, request: Request) -> None:
    if name not in MODELS:
        raise HTTPException(404, "Unknown speech model")
    svc = _svc(request)
    svc.models.delete(name)
    svc.audit.record("voice.model.delete", outcome="allowed", actor_type="user", target=name)


@router.get("/history", response_model=HistoryOut)
def history(request: Request, limit: Annotated[int, Query(ge=1, le=200)] = 50,
            offset: Annotated[int, Query(ge=0)] = 0) -> Any:
    items, total = _svc(request).history.list(limit, offset)
    return {"items": items, "total": total}


@router.delete("/history")
def history_clear(request: Request) -> dict[str, int]:
    svc = _svc(request)
    n = svc.history.clear()
    svc.audit.record("voice.history.clear", outcome="allowed", actor_type="user",
                     details={"sessions": n})
    return {"deleted": n}
