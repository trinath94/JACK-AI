"""Wake-word evaluation: missed detections and false activations.

Runs synthetic speech through the same path the engine uses
(high-pass → Silero VAD → segmenter → keyword-asr detector) and reports, per sensitivity:
  * miss rate on wake phrases ("Jack", "Hey Jack", "Jack, <command>", ...)
  * false activations on non-wake speech, including deliberate confusables
    ("jacket", "hijack", "Jackson", "Hey Jake"), expressed per hour of speech

Speech is synthesised with espeak-ng (several accents/voices/speeds) and mixed with white
noise at 20 dB and 10 dB SNR. Synthetic speech is NOT representative of real voices or
rooms; treat the numbers as a regression baseline, not a field estimate.

Usage (from repo root):
  JACK_TEST_MODELS_DIR=<models dir with tiny.en> \\
    uv run --project services/api python scripts/eval_wakeword.py docs/milestones/evidence-m3
"""

from __future__ import annotations

import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

from jack_api.voice.asr import WAKE_MODEL, ModelManager, Transcript
from jack_api.voice.audio import FRAME, SAMPLE_RATE
from jack_api.voice.dsp import HighPass, Segmenter
from jack_api.voice.vad import SileroVad
from jack_api.voice.wakeword import KeywordAsrDetector


class CachingRecognizer:
    """Wraps the model manager so each (segment, prompt) is transcribed once across all
    sensitivity levels; the detector logic itself is the shipped code."""

    def __init__(self, inner: ModelManager) -> None:
        self._inner = inner
        self._cache: dict[tuple[int, str | None], Transcript] = {}
        self.calls = 0

    def available(self, model: str) -> bool:
        return self._inner.available(model)

    def transcribe(self, audio: np.ndarray, model: str, *, prompt: str | None = None
                   ) -> Transcript:
        key = (hash(audio.tobytes()), prompt)
        if key not in self._cache:
            self.calls += 1
            self._cache[key] = self._inner.transcribe(audio, model, prompt=prompt)
        return self._cache[key]

VOICES = ["en-us", "en-gb", "en-gb-scotland", "en-gb-x-rp", "en-029", "en-us+f3", "en-gb+f4",
          "en-us+m5"]
SPEEDS = [140, 175]
NOISE_SNR_DB: list[float | None] = [None, 20.0, 10.0]
SENSITIVITIES = [0.3, 0.5, 0.7, 0.9]

POSITIVES = ["Jack.", "Hey Jack.", "Jack, open GitHub.", "Hey Jack, build a website.",
             "OK Jack, what's the status?"]

CONFUSABLES = [
    "Put on your jacket, it's cold.", "They tried to hijack the meeting.",
    "Jackson will join us later.", "Hey Jake, how are you?", "Hey Zack, over here.",
    "Can you check the logs?", "That is a black cat.", "We hit the jackpot today.",
    "Give it back to me.", "Jacqueline sent the report.", "The car jack is in the trunk.",
    "Tell Jack I will be late.", "I met Jack at the station yesterday.",
]
EVERYDAY = [
    "The weather is lovely today.", "Let's go for a walk in the park.",
    "Please send me the quarterly report.", "What time does the train leave?",
    "I need to buy some milk and bread.", "The meeting has been moved to Thursday.",
    "Can you turn the music down a little?", "My favourite colour is blue.",
    "We should deploy the new version tomorrow.", "Open the window, it's warm in here.",
    "The database migration finished successfully.", "Remind me to call my mother.",
    "How many people are coming to dinner?", "This coffee is too hot to drink.",
    "The server is running out of disk space.", "Have you seen my keys anywhere?",
    "Let's review the pull request after lunch.", "The children are playing outside.",
    "Turn left at the next traffic light.", "I'll be working from home on Friday.",
    "Hey, are you listening to me?", "OK, let's get started.",
    "Hello everyone, welcome to the call.", "Hi there, nice to meet you.",
]
NEG_VOICES = ["en-us", "en-gb", "en-gb-scotland", "en-us+f3"]


def synth(text: str, voice: str, wpm: int, tmp: Path) -> np.ndarray:
    raw, out = tmp / "raw.wav", tmp / "16k.wav"
    subprocess.run(["espeak-ng", "-v", voice, "-s", str(wpm), "-w", str(raw), text],  # noqa: S603,S607
                   check=True, capture_output=True)
    subprocess.run(["sox", str(raw), "-r", str(SAMPLE_RATE), "-c", "1", "-b", "16", str(out)],  # noqa: S603,S607
                   check=True, capture_output=True)
    with wave.open(str(out)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    pad = np.zeros(int(0.6 * SAMPLE_RATE), np.float32)
    return np.concatenate([pad, pcm, pad, pad])


def add_noise(x: np.ndarray, snr_db: float | None, rng: random.Random) -> np.ndarray:
    if snr_db is None:
        return x
    sig = x[np.abs(x) > 1]
    p_sig = float(np.mean(sig**2)) if sig.size else 1.0
    p_noise = p_sig / (10 ** (snr_db / 10))
    noise = np.array([rng.gauss(0, 1) for _ in range(x.shape[0])], np.float32) * math.sqrt(p_noise)
    return x + noise


def segments(x: np.ndarray) -> list[np.ndarray]:
    pcm = np.clip(x, -32768, 32767).astype(np.int16)
    hp, vad, seg = HighPass(), SileroVad(), Segmenter(end_silence_ms=500, max_s=12.0)
    out = []
    for i in range(0, len(pcm) - FRAME + 1, FRAME):
        f = hp(pcm[i:i + FRAME])
        s = seg.push(f, vad.prob(f))
        if s is not None:
            out.append(s.audio)
    return out


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out_dir.mkdir(parents=True, exist_ok=True)
    models = os.environ.get("JACK_TEST_MODELS_DIR")
    if not models or not shutil.which("espeak-ng") or not shutil.which("sox"):
        print("needs JACK_TEST_MODELS_DIR, espeak-ng and sox", file=sys.stderr)
        return 2
    mm = ModelManager(Path(models), lambda *_: None)
    rec = CachingRecognizer(mm)
    detector = KeywordAsrDetector(rec)
    rng = random.Random(1234)

    samples: list[dict[str, object]] = []
    for text in POSITIVES:
        for v in VOICES:
            for wpm in SPEEDS:
                for snr in NOISE_SNR_DB:
                    samples.append({"text": text, "voice": v, "wpm": wpm, "snr": snr, "wake": True,
                                    "kind": "wake"})
    for kind, texts in (("confusable", CONFUSABLES), ("everyday", EVERYDAY)):
        for text in texts:
            for v in NEG_VOICES:
                for snr in NOISE_SNR_DB:
                    samples.append({"text": text, "voice": v, "wpm": 165, "snr": snr,
                                    "wake": False, "kind": kind})

    t0 = time.time()
    neg_seconds = 0.0
    with tempfile.TemporaryDirectory() as tmp:
        for n, s in enumerate(samples, 1):
            x = add_noise(synth(str(s["text"]), str(s["voice"]), int(s["wpm"]),  # type: ignore[call-overload]
                                Path(tmp)), s["snr"], rng)  # type: ignore[arg-type]
            if not s["wake"]:
                neg_seconds += x.shape[0] / SAMPLE_RATE
            segs = segments(x)
            s["detected"] = {sens: any(detector.check(a, sens).detected for a in segs)
                             for sens in SENSITIVITIES}
            s["transcripts"] = [detector.check(a, 0.5).transcript for a in segs]
            if n % 50 == 0:
                print(f"{n}/{len(samples)} samples ({time.time() - t0:.0f}s)", flush=True)

    def detected(s: dict[str, object], sens: float) -> bool:
        return bool(s["detected"][sens])  # type: ignore[index]

    neg_hours = neg_seconds / 3600
    rows = []
    for sens in SENSITIVITIES:
        pos = [s for s in samples if s["wake"]]
        neg = [s for s in samples if not s["wake"]]
        misses = [s for s in pos if not detected(s, sens)]
        fas = [s for s in neg if detected(s, sens)]
        by_snr = {}
        for snr in NOISE_SNR_DB:
            p = [s for s in pos if s["snr"] == snr]
            by_snr["clean" if snr is None else f"{int(snr)}dB"] = round(
                100 * sum(not detected(s, sens) for s in p) / len(p), 1)
        rows.append({
            "sensitivity": sens, "positives": len(pos), "misses": len(misses),
            "miss_rate_pct": round(100 * len(misses) / len(pos), 1),
            "miss_rate_by_noise_pct": by_snr,
            "negatives": len(neg), "false_activations": len(fas),
            "false_activations_per_hour": round(len(fas) / neg_hours, 1) if neg_hours else None,
            "false_activations_everyday": sum(s["kind"] == "everyday" for s in fas),
            "false_activations_confusable": sum(s["kind"] == "confusable" for s in fas),
            "false_activation_examples": sorted({str(s["text"]) for s in fas})[:10],
            "missed_examples": sorted({f'{s["text"]} [{s["voice"]}, {s["snr"]}]'
                                       for s in misses})[:10],
        })
    report = {"engine": "keyword-asr", "wake_model": WAKE_MODEL, "transcriptions": rec.calls, "samples": len(samples),
              "negative_speech_minutes": round(neg_seconds / 60, 1),
              "runtime_s": round(time.time() - t0), "results": rows,
              "caveat": "Synthetic espeak-ng speech with white noise; not a field estimate."}
    (out_dir / "wakeword-eval.json").write_text(json.dumps(report, indent=2))
    (out_dir / "wakeword-eval-samples.json").write_text(json.dumps(
        [{k: s[k] for k in ("text", "voice", "wpm", "snr", "wake", "kind", "transcripts", "detected")}
         for s in samples], indent=1))

    lines = ["# Wake-word evaluation (synthetic)", "",
             f"Engine `keyword-asr` as shipped (Silero VAD + Whisper {WAKE_MODEL}; "
             "biased pass + veto from sensitivity 0.5). "
             f"{len(samples)} clips: "
             f"{len(POSITIVES)} wake phrases × {len(VOICES)} voices × {len(SPEEDS)} speeds × "
             f"3 noise levels; {len(CONFUSABLES) + len(EVERYDAY)} non-wake sentences "
             f"({len(CONFUSABLES)} confusables) × {len(NEG_VOICES)} voices × 3 noise levels "
             f"= {neg_seconds / 60:.1f} min of non-wake speech.", "",
             "| Sensitivity | Miss rate | clean / 20 dB / 10 dB | False activations (everyday / confusable) | per hour of speech |",
             "|---|---|---|---|---|"]
    for r in rows:
        m = r["miss_rate_by_noise_pct"]
        lines.append(f"| {r['sensitivity']} | {r['miss_rate_pct']}% ({r['misses']}/{r['positives']}) | "
                     f"{m['clean']}% / {m['20dB']}% / {m['10dB']}% | "
                     f"{r['false_activations']}/{r['negatives']} ({r['false_activations_everyday']} / "
                     f"{r['false_activations_confusable']}) | {r['false_activations_per_hour']} |")
    lines += ["", "False-activation phrases at each sensitivity:", ""]
    for r in rows:
        lines.append(f"- **{r['sensitivity']}**: " + (", ".join(f'"{e}"' for e in r["false_activation_examples"]) or "none"))
    lines += ["", "> " + report["caveat"] + " Real voices, accents, rooms and microphones "
              "need the acceptance test A on Windows (docs/architecture/ACCEPTANCE_TESTS.md).", ""]
    (out_dir / "wakeword-eval.md").write_text("\n".join(lines))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
