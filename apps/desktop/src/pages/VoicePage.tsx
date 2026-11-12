import type { AudioDevice } from "@jack/shared-types";
import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { PushToTalk } from "../components/PushToTalk";
import { Card, Meter, Pill } from "../components/ui";
import { VoiceOrb } from "../components/VoiceOrb";
import { ApiRequestError } from "../lib/api";
import { useBackend } from "../lib/backend";

export function VoicePage({ shortcut }: { shortcut: string | null }) {
  const { api, voice, voiceLevel, lastUtterance, voiceError } = useBackend();
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadDevices = useCallback(async () => {
    if (!api) return;
    setDevices(await api.voiceDevices());
  }, [api]);
  useEffect(() => void loadDevices().catch(() => {}), [loadDevices]);

  async function update(patch: Parameters<NonNullable<typeof api>["updateVoiceSettings"]>[0]) {
    if (!api) return;
    setError(null);
    try {
      await api.updateVoiceSettings(patch);
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : "Could not save setting");
    }
  }

  if (!voice) {
    return <Card><p className="text-sm text-[var(--muted)]">Voice settings are available once the JACK service is running.</p></Card>;
  }
  const s = voice.settings;
  const caps = voice.capabilities;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Microphone test" className="flex flex-col items-center gap-4">
        <VoiceOrb state={voice.state} level={voiceLevel} size={120} />
        <div className="w-full max-w-xs">
          <Meter label="Input level" value={voice.state === "listening" ? voiceLevel * 100 : 0} />
        </div>
        <PushToTalk shortcut={shortcut} />
        {lastUtterance && (
          <p className="text-center text-xs text-[var(--muted)]">
            Last capture: {(lastUtterance.captured_ms / 1000).toFixed(1)} s ({lastUtterance.stopped_by.replace("_", " ")}). {lastUtterance.detail}
          </p>
        )}
        {voiceError && <p role="alert" className="text-sm text-rose-500">{voiceError}</p>}
      </Card>

      <Card title="Input">
        <div className="space-y-4 text-sm">
          <div>
            <div className="mb-1 flex items-center justify-between">
              <label htmlFor="mic" className="font-medium">Microphone</label>
              <button type="button" onClick={() => void loadDevices()} className="inline-flex items-center gap-1 text-xs text-[var(--muted)]" aria-label="Refresh microphones">
                <RefreshCw className="h-3 w-3" aria-hidden /> Refresh
              </button>
            </div>
            <select
              id="mic"
              value={s.input_device_id ?? ""}
              onChange={(e) => void update({ input_device_id: e.target.value || null })}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
            >
              <option value="">System default</option>
              {devices.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} ({d.host_api}){d.is_default ? " — default" : ""}
                </option>
              ))}
            </select>
            {devices.length === 0 && (
              <p className="mt-1 text-xs text-amber-600 dark:text-amber-300">{caps.capture_detail ?? "No microphone found."}</p>
            )}
          </div>
          <Toggle label="Mute microphone" checked={s.muted} onChange={(v) => void update({ muted: v })} hint="Also available from the tray menu." />
          <Toggle
            label="Privacy mode"
            checked={s.privacy_mode}
            onChange={(v) => void update({ privacy_mode: v })}
            hint="Turns the microphone off completely. From Milestone 3 it also stops transcripts being kept."
          />
          <div>
            <label htmlFor="maxlisten" className="font-medium">Maximum listening time: {s.max_listen_s} s</label>
            <input
              id="maxlisten"
              type="range"
              min={5}
              max={120}
              step={5}
              value={s.max_listen_s}
              onChange={(e) => void update({ max_listen_s: Number(e.target.value) })}
              className="mt-1 w-full accent-[var(--accent)]"
            />
            <p className="text-xs text-[var(--muted)]">The microphone closes automatically after this, even if the key is still held.</p>
          </div>
          {error && <p role="alert" className="text-rose-500">{error}</p>}
        </div>
      </Card>

      <Card title="Wake word">
        <div className="space-y-4 text-sm">
          <Toggle
            label='Listen for "Jack" / "Hey Jack"'
            checked={s.wake_word_enabled}
            disabled={!caps.wake_word}
            onChange={(v) => void update({ wake_word_enabled: v })}
            hint={caps.wake_word ? undefined : `Wake-word detection runs locally and arrives in Milestone ${caps.pending_milestone}. Your preference is saved now.`}
          />
          <div>
            <label htmlFor="sens" className="font-medium">Sensitivity: {s.wake_word_sensitivity.toFixed(2)}</label>
            <input
              id="sens"
              type="range"
              min={0.1}
              max={0.9}
              step={0.05}
              value={s.wake_word_sensitivity}
              onChange={(e) => void update({ wake_word_sensitivity: Number(e.target.value) })}
              className="mt-1 w-full accent-[var(--accent)]"
            />
            <p className="text-xs text-[var(--muted)]">Higher catches more quiet wake words but risks false activations.</p>
          </div>
        </div>
      </Card>

      <Card title="Capabilities">
        <ul className="space-y-2 text-sm" aria-label="Voice capabilities">
          <Cap name="Microphone capture & level" ok={caps.capture} detail={caps.capture_detail} />
          <Cap name="Wake word (local)" ok={caps.wake_word} pending={caps.pending_milestone} />
          <Cap name="Speech recognition" ok={caps.speech_recognition} pending={caps.pending_milestone} />
          <Cap name="Spoken replies" ok={caps.speech_synthesis} pending={caps.pending_milestone} />
        </ul>
        <p className="mt-4 text-xs text-[var(--muted)]">
          Audio stays on this computer. In this version captured audio is reduced to a level reading and discarded immediately; nothing is recorded or sent anywhere.
        </p>
      </Card>
    </div>
  );
}

function Toggle({ label, checked, onChange, hint, disabled }: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
  disabled?: boolean;
}) {
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

function Cap({ name, ok, detail, pending }: { name: string; ok: boolean; detail?: string | null; pending?: number }) {
  return (
    <li className="flex items-center justify-between gap-3">
      <span>{name}</span>
      {ok ? <Pill tone="ok">available</Pill> : pending ? <Pill tone="muted">Milestone {pending}</Pill> : <Pill tone="bad">{detail ?? "unavailable"}</Pill>}
    </li>
  );
}
