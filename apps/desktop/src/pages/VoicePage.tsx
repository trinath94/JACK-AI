import type { AudioDevice, SpeechModel, TtsVoice, VoiceSession, VoiceSettingsPatch } from "@jack/shared-types";
import { Download, RefreshCw, Square, Trash2, Volume2 } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { PushToTalk } from "../components/PushToTalk";
import { Card, Meter, Pill, formatTime } from "../components/ui";
import { VoiceOrb } from "../components/VoiceOrb";
import { ApiRequestError } from "../lib/api";
import { useBackend } from "../lib/backend";

const ASR_CHOICES = [
  { value: "small.en", label: "small.en — most accurate (recommended)" },
  { value: "base.en", label: "base.en — faster, for slower PCs" },
  { value: "tiny.en", label: "tiny.en — fastest, least accurate" },
] as const;

export function VoicePage({ shortcut }: { shortcut: string | null }) {
  const { api, voice, voiceLevel, lastUtterance, lastReply, voiceError, models, activity } = useBackend();
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [voices, setVoices] = useState<TtsVoice[]>([]);
  const [history, setHistory] = useState<VoiceSession[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadDevices = useCallback(async () => {
    if (!api) return;
    setDevices(await api.voiceDevices());
  }, [api]);
  useEffect(() => void loadDevices().catch(() => {}), [loadDevices]);
  useEffect(() => {
    api?.ttsVoices().then(setVoices).catch(() => {});
  }, [api]);
  useEffect(() => {
    if (!api) return;
    const t = setTimeout(() => api.voiceHistory(20).then((h) => setHistory(h.items)).catch(() => {}), 300);
    return () => clearTimeout(t);
  }, [api, activity]);

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : "Action failed");
    }
  }
  const update = (patch: VoiceSettingsPatch) => run(() => api!.updateVoiceSettings(patch));

  if (!voice || !api) {
    return <Card><p className="text-sm text-[var(--muted)]">Voice settings are available once the JACK service is running.</p></Card>;
  }
  const s = voice.settings;
  const caps = voice.capabilities;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Talk to JACK" className="flex flex-col items-center gap-4">
        <VoiceOrb state={voice.state} level={voiceLevel} size={120} />
        <div className="w-full max-w-xs">
          <Meter label="Input level" value={voice.state === "listening" ? voiceLevel * 100 : 0} />
        </div>
        <PushToTalk shortcut={shortcut} />
        {(lastUtterance?.transcript || lastReply) && (
          <div className="w-full space-y-1 rounded-lg bg-[var(--hover)] px-3 py-2 text-sm" data-testid="voice-last-exchange">
            {lastUtterance?.transcript && <p><span className="font-semibold">You:</span> {lastUtterance.transcript}</p>}
            {lastReply && <p><span className="font-semibold text-[var(--accent)]">JACK:</span> {lastReply}</p>}
          </div>
        )}
        {(voiceError || error) && <p role="alert" className="text-sm text-rose-500">{voiceError ?? error}</p>}
      </Card>

      <Card title="Speech models">
        <p className="mb-3 text-xs text-[var(--muted)]">
          Speech is recognised on this computer with open-source Whisper models (MIT licence). Models are downloaded
          from Hugging Face only when you click Download, then work offline.
        </p>
        <ul className="space-y-3" aria-label="Speech models">
          {models.map((m) => (
            <ModelRow key={m.name} m={m} onDownload={() => run(() => api.downloadSpeechModel(m.name))} onDelete={() => run(() => api.deleteSpeechModel(m.name))} />
          ))}
        </ul>
      </Card>

      <Card title="Microphone">
        <div className="space-y-4 text-sm">
          <div>
            <div className="mb-1 flex items-center justify-between">
              <label htmlFor="mic" className="font-medium">Microphone</label>
              <button type="button" onClick={() => void loadDevices()} className="inline-flex items-center gap-1 text-xs text-[var(--muted)]" aria-label="Refresh microphones">
                <RefreshCw className="h-3 w-3" aria-hidden /> Refresh
              </button>
            </div>
            <select id="mic" value={s.input_device_id ?? ""} onChange={(e) => void update({ input_device_id: e.target.value || null })} className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
              <option value="">System default</option>
              {devices.map((d) => (
                <option key={d.id} value={d.id}>{d.name} ({d.host_api}){d.is_default ? " — default" : ""}</option>
              ))}
            </select>
            {!caps.capture && <p className="mt-1 text-xs text-amber-600 dark:text-amber-300">{caps.capture_detail ?? "No microphone found."}</p>}
          </div>
          <Toggle label="Mute microphone" checked={s.muted} onChange={(v) => void update({ muted: v })} hint="Also available from the tray menu." />
          <Toggle label="Privacy mode" checked={s.privacy_mode} onChange={(v) => void update({ privacy_mode: v })} hint="Microphone off, no transcripts kept, no spoken replies." />
          <Range id="maxlisten" label={`Maximum push-to-talk time: ${s.max_listen_s} s`} min={5} max={120} step={5} value={s.max_listen_s} onChange={(v) => void update({ max_listen_s: v })} />
        </div>
      </Card>

      <Card title="Wake word">
        <div className="space-y-4 text-sm">
          <Toggle
            label='Listen for "Jack" / "Hey Jack"'
            checked={s.wake_word_enabled}
            onChange={(v) => void update({ wake_word_enabled: v })}
            hint={
              caps.wake_word
                ? "The microphone stays open and audio is analysed on this computer only. Say “Jack”, wait for “Yes, I'm listening”, then speak — or say it in one go: “Jack, open GitHub”."
                : (caps.wake_word_detail ?? undefined)
            }
          />
          <Range id="sens" label={`Sensitivity: ${s.wake_word_sensitivity.toFixed(2)}`} min={0.1} max={0.9} step={0.05} value={s.wake_word_sensitivity} onChange={(v) => void update({ wake_word_sensitivity: v })} hint="Higher accepts less clear pronunciations (and more false activations). See the evaluation in the Milestone 3 report." />
          <p className="text-xs text-[var(--muted)]">Detector: {caps.wake_word_engine === "keyword-asr" ? "local keyword recognition (Whisper tiny.en)" : caps.wake_word_engine}</p>
        </div>
      </Card>

      <Card title="Recognition">
        <div className="space-y-4 text-sm">
          <div>
            <label htmlFor="asr" className="mb-1 block font-medium">Command model</label>
            <select id="asr" value={s.asr_model} onChange={(e) => void update({ asr_model: e.target.value as VoiceSettingsPatch["asr_model"] })} className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
              {ASR_CHOICES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
            {!caps.speech_recognition && <p className="mt-1 text-xs text-amber-600 dark:text-amber-300">{caps.speech_recognition_detail}</p>}
          </div>
          <Range id="eos" label={`Pause that ends a command: ${(s.end_of_speech_ms / 1000).toFixed(1)} s`} min={300} max={3000} step={100} value={s.end_of_speech_ms} onChange={(v) => void update({ end_of_speech_ms: v })} />
        </div>
      </Card>

      <Card title="Spoken replies">
        <div className="space-y-4 text-sm">
          <Toggle label="JACK speaks its replies" checked={s.tts_enabled} onChange={(v) => void update({ tts_enabled: v })} hint={caps.speech_synthesis ? undefined : (caps.speech_synthesis_detail ?? undefined)} disabled={!caps.speech_synthesis} />
          <div>
            <label htmlFor="ttsvoice" className="mb-1 block font-medium">Voice</label>
            <select id="ttsvoice" value={s.tts_voice_id ?? ""} disabled={!voices.length} onChange={(e) => void update({ tts_voice_id: e.target.value || null })} className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
              <option value="">Default voice</option>
              {voices.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          </div>
          <Range id="rate" label={`Speaking speed: ${s.tts_rate.toFixed(2)}×`} min={0.5} max={2} step={0.05} value={s.tts_rate} onChange={(v) => void update({ tts_rate: v })} />
          <div className="flex gap-2">
            <button type="button" disabled={!caps.speech_synthesis} onClick={() => void run(() => api.speak("Hello, I'm JACK. Give the command, and I'll deliver."))} className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium hover:bg-[var(--hover)] disabled:opacity-50">
              <Volume2 className="h-3.5 w-3.5" aria-hidden /> Test voice
            </button>
            <button type="button" disabled={voice.state !== "speaking"} onClick={() => void run(() => api.stopSpeaking())} className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium hover:bg-[var(--hover)] disabled:opacity-50">
              <Square className="h-3.5 w-3.5" aria-hidden /> Stop speaking
            </button>
          </div>
          <p className="text-xs text-[var(--muted)]">Engine: {caps.speech_synthesis_engine === "sapi" ? "Windows speech (SAPI)" : caps.speech_synthesis_engine}. Pressing push-to-talk interrupts JACK.</p>
        </div>
      </Card>

      <Card
        title="Conversation history"
        action={
          <button type="button" disabled={!history.length} onClick={() => void run(async () => { await api.clearVoiceHistory(); setHistory([]); })} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-[var(--muted)] hover:bg-[var(--hover)] disabled:opacity-40">
            <Trash2 className="h-3 w-3" aria-hidden /> Clear
          </button>
        }
      >
        <div className="mb-3 space-y-3 text-sm">
          <Toggle label="Keep conversation history" checked={s.keep_history} onChange={(v) => void update({ keep_history: v })} hint={`Text only — audio is never stored. Kept for ${s.history_retention_days} days.`} />
          <Range id="ret" label={`Keep for ${s.history_retention_days} days`} min={1} max={365} step={1} value={s.history_retention_days} onChange={(v) => void update({ history_retention_days: v })} />
        </div>
        {history.length === 0 ? (
          <p className="text-sm text-[var(--muted)]">No conversations yet.</p>
        ) : (
          <ul className="max-h-80 space-y-3 overflow-y-auto" aria-label="Conversation history">
            {history.map((h) => (
              <li key={h.id} className="rounded-lg border border-[var(--border)] p-3 text-sm">
                <p className="mb-1 text-[11px] text-[var(--muted)]">{formatTime(h.started_at)} · {h.trigger === "wake" ? "wake word" : "push-to-talk"}{h.task_id ? " · task created" : ""}</p>
                {h.turns.map((t, i) => (
                  <p key={i}><span className={`font-semibold ${t.role === "jack" ? "text-[var(--accent)]" : ""}`}>{t.role === "jack" ? "JACK" : "You"}:</span> {t.text}</p>
                ))}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Capabilities">
        <ul className="space-y-2 text-sm" aria-label="Voice capabilities">
          <Cap name="Microphone" ok={caps.capture} detail={caps.capture_detail} />
          <Cap name="Wake word (local)" ok={caps.wake_word} detail={caps.wake_word_detail} />
          <Cap name="Speech recognition (local)" ok={caps.speech_recognition} detail={caps.speech_recognition_detail} />
          <Cap name="Spoken replies" ok={caps.speech_synthesis} detail={caps.speech_synthesis_detail} />
        </ul>
        <p className="mt-4 text-xs text-[var(--muted)]">
          Audio never leaves this computer and is never saved. Only the text of conversations is kept, if you allow it.
        </p>
      </Card>
    </div>
  );
}

function ModelRow({ m, onDownload, onDelete }: { m: SpeechModel; onDownload: () => void; onDelete: () => void }) {
  const pct = Math.min(100, (m.downloaded_mb / m.size_mb) * 100);
  return (
    <li className="text-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium">{m.name} <span className="text-xs font-normal text-[var(--muted)]">· {m.size_mb} MB</span></p>
          <p className="truncate text-xs text-[var(--muted)]">{m.purpose}</p>
        </div>
        {m.status === "ready" ? (
          <span className="flex items-center gap-2">
            <Pill tone="ok">ready</Pill>
            <button type="button" onClick={onDelete} aria-label={`Delete ${m.name}`} className="rounded p-1 text-[var(--muted)] hover:bg-[var(--hover)]"><Trash2 className="h-3.5 w-3.5" /></button>
          </span>
        ) : m.status === "downloading" ? (
          <Pill tone="accent">downloading</Pill>
        ) : (
          <button type="button" onClick={onDownload} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-white">
            <Download className="h-3.5 w-3.5" aria-hidden /> {m.status === "error" ? "Retry" : "Download"}
          </button>
        )}
      </div>
      {m.status === "downloading" && <div className="mt-2"><Meter label={`Downloading ${m.name}`} value={pct} detail={`${m.downloaded_mb.toFixed(0)} / ${m.size_mb} MB`} /></div>}
      {m.status === "error" && <p className="mt-1 text-xs text-rose-500">{m.error}</p>}
    </li>
  );
}

function Toggle({ label, checked, onChange, hint, disabled }: { label: string; checked: boolean; onChange: (v: boolean) => void; hint?: string; disabled?: boolean }) {
  return (
    <div>
      <label className={`flex items-center justify-between gap-4 font-medium ${disabled ? "opacity-60" : ""}`}>
        {label}
        <input type="checkbox" role="switch" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
      </label>
      {hint && <p className="mt-0.5 text-xs text-[var(--muted)]">{hint}</p>}
    </div>
  );
}

function Range({ id, label, min, max, step, value, onChange, hint }: { id: string; label: ReactNode; min: number; max: number; step: number; value: number; onChange: (v: number) => void; hint?: string }) {
  // Commit on release so dragging doesn't send a request per pixel.
  const [local, setLocal] = useState(value);
  useEffect(() => setLocal(value), [value]);
  return (
    <div>
      <label htmlFor={id} className="font-medium">{label}</label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={local}
        onChange={(e) => setLocal(Number(e.target.value))}
        onPointerUp={() => local !== value && onChange(local)}
        onKeyUp={() => local !== value && onChange(local)}
        onBlur={() => local !== value && onChange(local)}
        className="mt-1 w-full accent-[var(--accent)]"
      />
      {hint && <p className="text-xs text-[var(--muted)]">{hint}</p>}
    </div>
  );
}

function Cap({ name, ok, detail }: { name: string; ok: boolean; detail?: string | null }) {
  return (
    <li className="flex items-center justify-between gap-3">
      <span>{name}</span>
      {ok ? <Pill tone="ok">available</Pill> : <span className="max-w-[60%] text-right text-xs text-amber-600 dark:text-amber-300">{detail ?? "unavailable"}</span>}
    </li>
  );
}
