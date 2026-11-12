"""Text-to-speech with interruptible playback.

* Windows: native SAPI 5 voices through COM (comtypes). Playback is asynchronous and can be
  purged mid-sentence.
* Linux (development / CI): espeak-ng, if installed.
* Otherwise: unavailable (reported, never faked).

Premium/cloud voices are a provider slot for later milestones (they need credentials).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger(__name__)


class TtsError(Exception):
    """Speech could not be played (no output device, engine failure)."""


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    language: str | None = None


class TtsBackend(Protocol):
    engine: str

    def available(self) -> tuple[bool, str | None]: ...
    def voices(self) -> list[Voice]: ...
    def speak(self, text: str, voice_id: str | None, rate: float,
              cancel: threading.Event) -> bool:
        """Speak synchronously; return False if interrupted via ``cancel``."""
        ...


class NullTts:
    engine = "none"

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def available(self) -> tuple[bool, str | None]:
        return False, self._reason

    def voices(self) -> list[Voice]:
        return []

    def speak(self, text: str, voice_id: str | None, rate: float,
              cancel: threading.Event) -> bool:
        return False


class EspeakTts:
    engine = "espeak-ng"

    def __init__(self, binary: str) -> None:
        self._bin = binary

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def voices(self) -> list[Voice]:
        return [Voice("en-us", "English (US)", "en-US"), Voice("en-gb", "English (UK)", "en-GB")]

    def speak(self, text: str, voice_id: str | None, rate: float,
              cancel: threading.Event) -> bool:
        wpm = str(int(175 * rate))
        proc = subprocess.Popen([self._bin, "-v", voice_id or "en-us", "-s", wpm, "--", text],  # noqa: S603
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        while proc.poll() is None:
            if cancel.wait(0.05):
                proc.terminate()
                proc.wait(2)
                return False
        err = (proc.stderr.read() if proc.stderr else b"").decode(errors="replace")
        # espeak-ng exits 0 even when it cannot open an audio device; don't report success.
        if proc.returncode != 0 or "error:" in err.lower():
            last = [ln for ln in err.strip().splitlines() if ln.strip()][-1:] or ["unknown error"]
            raise TtsError(f"espeak-ng could not play audio: {last[0]}")
        return True


class SapiTts:
    """Windows SAPI 5 via COM. COM objects live on one dedicated thread."""

    engine = "sapi"
    SVSF_ASYNC = 1
    SVSF_PURGE = 2

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._error: str | None = None
        self._voices: list[Voice] = []
        try:
            self._voices = self._with_com(self._list_voices)
        except Exception as exc:  # noqa: BLE001 - COM/registration errors
            self._error = f"Windows speech unavailable: {exc}"

    def _with_com(self, fn: Any) -> Any:
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        try:
            return fn(comtypes.client.CreateObject("SAPI.SpVoice"))
        finally:
            comtypes.CoUninitialize()

    @staticmethod
    def _list_voices(sp: Any) -> list[Voice]:
        out = []
        tokens = sp.GetVoices()
        for i in range(tokens.Count):
            t = tokens.Item(i)
            out.append(Voice(t.Id, t.GetDescription()))
        return out

    def available(self) -> tuple[bool, str | None]:
        if self._error:
            return False, self._error
        if not self._voices:
            return False, "No Windows voices are installed"
        return True, None

    def voices(self) -> list[Voice]:
        return list(self._voices)

    def speak(self, text: str, voice_id: str | None, rate: float,
              cancel: threading.Event) -> bool:
        def run(sp: Any) -> bool:
            if voice_id:
                tokens = sp.GetVoices()
                for i in range(tokens.Count):
                    if tokens.Item(i).Id == voice_id:
                        sp.Voice = tokens.Item(i)
                        break
            # SAPI rate is -10..10; map 0.5x..2x onto roughly -5..+5.
            sp.Rate = max(-10, min(10, round((rate - 1.0) * 10)))
            sp.Speak(text, self.SVSF_ASYNC)
            while not sp.WaitUntilDone(50):
                if cancel.is_set():
                    sp.Speak("", self.SVSF_ASYNC | self.SVSF_PURGE)
                    return False
            return True

        with self._lock:
            return bool(self._with_com(run))


def default_tts() -> TtsBackend:
    if sys.platform == "win32":
        return SapiTts()
    binary = shutil.which("espeak-ng")
    if binary:
        return EspeakTts(binary)
    return NullTts("No speech engine found (install espeak-ng on Linux)")
