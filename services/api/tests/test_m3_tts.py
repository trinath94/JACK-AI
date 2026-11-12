"""Text-to-speech backends on the real platform engines."""

from __future__ import annotations

import shutil
import sys
import threading
import time

import pytest

from jack_api.voice.tts import EspeakTts, NullTts, SapiTts, TtsError, default_tts


@pytest.mark.skipif(not shutil.which("espeak-ng") or sys.platform == "win32",
                    reason="espeak-ng (Linux) not installed")
def test_espeak_speaks_and_can_be_interrupted() -> None:
    tts = EspeakTts(shutil.which("espeak-ng") or "")
    assert tts.available() == (True, None)
    assert [v.id for v in tts.voices()] == ["en-us", "en-gb"]
    try:
        assert tts.speak("Hi.", None, 2.0, threading.Event()) is True
    except TtsError as exc:
        pytest.skip(f"no audio output device here: {exc}")
    cancel = threading.Event()
    threading.Timer(0.2, cancel.set).start()
    t = time.monotonic()
    assert tts.speak("This is a long sentence that will be cut off well before it ends. " * 5,
                     None, 1.0, cancel) is False
    assert time.monotonic() - t < 2


@pytest.mark.skipif(sys.platform != "win32", reason="Windows SAPI only")
def test_sapi_lists_voices_on_windows() -> None:
    tts = SapiTts()
    ok, detail = tts.available()
    print("SAPI available:", ok, detail, [v.name for v in tts.voices()])
    assert ok, detail
    assert tts.voices()


def test_null_backend_reports_reason() -> None:
    n = NullTts("nothing here")
    assert n.available() == (False, "nothing here")
    assert n.speak("x", None, 1.0, threading.Event()) is False


def test_default_backend_matches_platform() -> None:
    engine = default_tts().engine
    if sys.platform == "win32":
        assert engine == "sapi"
    else:
        assert engine in ("espeak-ng", "none")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell script")
def test_espeak_device_error_is_not_reported_as_spoken(tmp_path) -> None:  # type: ignore[no-untyped-def]
    fake = tmp_path / "espeak-ng"
    fake.write_text("#!/bin/sh\necho 'ALSA lib pcm.c: Unknown PCM default' >&2\n"
                    "echo 'error: No such file or directory' >&2\nexit 0\n")
    fake.chmod(0o755)
    with pytest.raises(TtsError, match="could not play audio"):
        EspeakTts(str(fake)).speak("hello", None, 1.0, threading.Event())
