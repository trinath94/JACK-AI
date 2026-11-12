import type { AuditEvent, TaskDetail } from "@jack/shared-types";
import { CornerDownLeft, RotateCcw, ShieldCheck, X } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode, type RefObject } from "react";
import { PushToTalk } from "../components/PushToTalk";
import { Card, Meter, Pill, formatBytes, formatTime, healthTone, taskTone } from "../components/ui";
import { VoiceOrb, type OrbState } from "../components/VoiceOrb";
import { ApiRequestError } from "../lib/api";
import { useBackend } from "../lib/backend";

const TERMINAL = new Set(["COMPLETED", "CANCELLED", "FAILED", "ROLLED_BACK"]);

// Integrations shown on the dashboard. None is configurable before its milestone; the
// dashboard says so instead of showing placeholder numbers.
const INTEGRATIONS = [
  { name: "Claude (Anthropic API / Claude Code)", milestone: 4 },
  { name: "API usage & cost", milestone: 4 },
  { name: "AI agents", milestone: 7 },
  { name: "GitHub", milestone: 9 },
  { name: "Servers (SSH)", milestone: 10 },
  { name: "Deployments", milestone: 13 },
];

export function HomePage({ commandRef, shortcut }: { commandRef: RefObject<HTMLInputElement | null>; shortcut: string | null }) {
  const { supervisor, socket, voice, voiceLevel, lastUtterance, voiceError, clearVoiceError } = useBackend();
  const online = supervisor.state === "running" && socket === "open";
  const orb: OrbState = !online ? "offline" : (voice?.state ?? "idle");

  return (
    <div className="grid gap-6 2xl:grid-cols-[1fr_400px] xl:grid-cols-[1fr_360px]">
      <div className="min-w-0 space-y-6">
        <Card className="flex flex-col items-center gap-5 py-8">
          <VoiceOrb state={orb} level={voiceLevel} />
          <PushToTalk shortcut={shortcut} />
          <VoiceChips />
          {lastUtterance && voice?.state !== "listening" && (
            <p className="max-w-xl rounded-lg bg-[var(--hover)] px-3 py-2 text-center text-xs text-[var(--muted)]" data-testid="last-utterance">
              Heard {(lastUtterance.captured_ms / 1000).toFixed(1)} s of audio. {lastUtterance.detail}
            </p>
          )}
          {voiceError && (
            <p role="alert" className="flex items-center gap-2 rounded-lg bg-rose-500/10 px-3 py-2 text-sm text-rose-600 dark:text-rose-300">
              {voiceError}
              <button type="button" onClick={clearVoiceError} aria-label="Dismiss voice error">
                <X className="h-3.5 w-3.5" />
              </button>
            </p>
          )}
          <CommandBox online={online} inputRef={commandRef} />
        </Card>
        <CurrentTask />
        <RecentTasks />
      </div>

      <div className="min-w-0 space-y-6">
        <ServiceCard />
        <ResourcesCard />
        <Card title="Approval queue">
          <p className="flex items-start gap-2 text-sm text-[var(--muted)]">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            No pending approvals. Agents request approvals for privileged actions from Milestone 6; each request will appear here, tied to one action, one target and an expiry.
          </p>
        </Card>
        <RecentEvents />
        <Card title="Integrations">
          <ul className="space-y-2 text-sm" aria-label="Integrations">
            {INTEGRATIONS.map((i) => (
              <li key={i.name} className="flex items-center justify-between gap-3">
                <span className="truncate">{i.name}</span>
                <Pill tone="muted">Milestone {i.milestone}</Pill>
              </li>
            ))}
          </ul>
        </Card>
        <ComponentsCard />
      </div>
    </div>
  );
}

function VoiceChips() {
  const { voice, api } = useBackend();
  const [deviceName, setDeviceName] = useState<string | null>(null);
  const selected = voice?.settings.input_device_id;
  const canCapture = voice?.capabilities.capture;
  useEffect(() => {
    if (!api || !voice) return;
    api
      .voiceDevices()
      .then((ds) => {
        const sel = voice.settings.input_device_id;
        const d = sel ? ds.find((x) => x.id === sel) : ds.find((x) => x.is_default);
        setDeviceName(d?.name ?? null);
      })
      .catch(() => setDeviceName(null));
  }, [api, selected, canCapture]);
  if (!voice) return null;
  const mic = voice.settings.privacy_mode
    ? { tone: "warn" as const, text: "Microphone: off (privacy mode)" }
    : voice.settings.muted
      ? { tone: "warn" as const, text: "Microphone: muted" }
      : voice.capabilities.capture
        ? { tone: "ok" as const, text: `Microphone: ${deviceName ?? "system default"}` }
        : { tone: "bad" as const, text: `Microphone: ${voice.capabilities.capture_detail ?? "unavailable"}` };
  return (
    <div className="flex flex-wrap justify-center gap-2">
      <Pill tone={mic.tone}>{mic.text}</Pill>
      <Pill tone="muted">Wake word "Jack": arrives in Milestone 3</Pill>
      <Pill tone="muted">Speech recognition: Milestone 3</Pill>
    </div>
  );
}

function CommandBox({ online, inputRef }: { online: boolean; inputRef: RefObject<HTMLInputElement | null> }) {
  const { api } = useBackend();
  const [command, setCommand] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!api || !command.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.createTask(command.trim(), "text");
      setCommand("");
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "Could not create task");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form onSubmit={submit} className="flex w-full max-w-2xl gap-2">
        <label htmlFor="command" className="sr-only">Command</label>
        <input
          id="command"
          ref={inputRef}
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          placeholder={online ? "Type a command for JACK…  (Ctrl+K)" : "Waiting for JACK service…"}
          disabled={!online || busy}
          maxLength={4000}
          className="min-w-0 flex-1 rounded-xl border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-[var(--accent)] disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={!online || busy || !command.trim()}
          className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
        >
          <CornerDownLeft className="h-4 w-4" aria-hidden /> Send
        </button>
      </form>
      <p className="max-w-2xl text-center text-xs text-[var(--muted)]">
        Commands are recorded as durable tasks. JACK starts planning and executing them from Milestones 5–7; until then they stay in <code>RECEIVED</code>.
      </p>
      {error && <p role="alert" className="text-sm text-rose-500">{error}</p>}
    </>
  );
}

function CurrentTask() {
  const { tasks, api } = useBackend();
  const current = tasks.find((t) => !TERMINAL.has(t.status)) ?? tasks[0];
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  useEffect(() => {
    if (!api || !current) return setDetail(null);
    let live = true;
    api.getTask(current.id).then((d) => live && setDetail(d)).catch(() => {});
    return () => {
      live = false;
    };
  }, [api, current?.id, current?.updated_at]);

  return (
    <Card title="Current task">
      {!current ? (
        <p className="text-sm text-[var(--muted)]">No active task.</p>
      ) : (
        <div className="space-y-3">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="truncate font-medium">{current.title}</p>
              <p className="font-mono text-[11px] text-[var(--muted)]">{current.id}</p>
            </div>
            <Pill tone={taskTone(current.status)}>{current.status}</Pill>
          </div>
          {detail && (
            <ol className="flex flex-wrap items-center gap-1.5 text-xs" aria-label="Task timeline">
              {detail.events.map((e, i) => (
                <li key={e.seq} className="flex items-center gap-1.5">
                  {i > 0 && <span className="text-[var(--muted)]">→</span>}
                  <span title={formatTime(e.occurred_at)}>
                    <Pill tone={taskTone(e.to_status)}>{e.to_status}</Pill>
                  </span>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </Card>
  );
}

function RecentTasks() {
  const { tasks } = useBackend();
  return (
    <Card title="Recent tasks">
      {tasks.length === 0 ? (
        <p className="text-sm text-[var(--muted)]">No tasks yet.</p>
      ) : (
        <ul className="divide-y divide-[var(--border)]" aria-label="Recent tasks">
          {tasks.slice(0, 6).map((t) => (
            <li key={t.id} className="flex items-center justify-between gap-4 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{t.title}</p>
                <p className="text-xs text-[var(--muted)]">{formatTime(t.created_at)} · {t.source}</p>
              </div>
              <Pill tone={taskTone(t.status)}>{t.status}</Pill>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ServiceCard() {
  const { supervisor, socket, health, restart } = useBackend();
  return (
    <Card
      title="JACK service"
      action={
        <button type="button" onClick={() => void restart()} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-[var(--muted)] hover:bg-[var(--hover)]">
          <RotateCcw className="h-3 w-3" aria-hidden /> Restart
        </button>
      }
    >
      <dl className="space-y-3 text-sm">
        <Row label="Supervisor"><Pill tone={healthTone(supervisor.state)}>{supervisor.state}</Pill></Row>
        <Row label="Live connection"><Pill tone={healthTone(socket)}>{socket}</Pill></Row>
        <Row label="Overall health"><Pill tone={healthTone(health?.status)}>{health?.status ?? "unknown"}</Pill></Row>
        <Row label="Restarts">{supervisor.restarts}</Row>
      </dl>
      {supervisor.lastError && (
        <p className="mt-3 rounded-lg bg-rose-500/10 p-2 text-xs text-rose-600 dark:text-rose-300">{supervisor.lastError}</p>
      )}
    </Card>
  );
}

function ResourcesCard() {
  const { metrics } = useBackend();
  return (
    <Card title="System resources">
      {!metrics ? (
        <p className="text-sm text-[var(--muted)]">No data yet.</p>
      ) : (
        <div className="space-y-3" aria-label="System resources">
          <Meter label={`CPU (${metrics.cpu_count} cores)`} value={metrics.cpu_percent} />
          <Meter
            label="Memory"
            value={metrics.memory_percent}
            detail={`${formatBytes(metrics.memory_used_bytes)} / ${formatBytes(metrics.memory_total_bytes)}`}
          />
          <Meter label="Disk (data drive)" value={metrics.disk_percent} detail={`${formatBytes(metrics.disk_free_bytes)} free`} />
          <p className="text-xs text-[var(--muted)]">
            JACK service: {formatBytes(metrics.service_rss_bytes)} RAM · {metrics.service_cpu_percent.toFixed(0)}% CPU
          </p>
        </div>
      )}
    </Card>
  );
}

function RecentEvents() {
  const { api, activity } = useBackend();
  const [events, setEvents] = useState<AuditEvent[]>([]);
  useEffect(() => {
    if (!api) return;
    const t = setTimeout(() => {
      api.audit(6).then((r) => setEvents(r.items)).catch(() => {});
    }, 300); // coalesce bursts of activity
    return () => clearTimeout(t);
  }, [api, activity]);
  return (
    <Card title="Recent events">
      {events.length === 0 ? (
        <p className="text-sm text-[var(--muted)]">No events yet.</p>
      ) : (
        <ul className="space-y-2 text-sm" aria-label="Recent events">
          {events.map((e) => (
            <li key={e.seq} className="flex items-center justify-between gap-3">
              <span className="min-w-0 truncate">
                <span className="font-mono text-xs">{e.action}</span>
                <span className="ml-2 text-xs text-[var(--muted)]">{formatTime(e.occurred_at)}</span>
              </span>
              <Pill tone={e.outcome === "denied" ? "bad" : e.outcome === "error" ? "warn" : "muted"}>{e.outcome}</Pill>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ComponentsCard() {
  const { health } = useBackend();
  return (
    <Card title="Components">
      {!health ? (
        <p className="text-sm text-[var(--muted)]">No health data yet.</p>
      ) : (
        <ul className="space-y-2" aria-label="Component health">
          {health.components.map((c) => (
            <li key={c.name} className="flex items-center justify-between gap-3 text-sm">
              <span className="capitalize">{c.name}</span>
              <span className="flex min-w-0 items-center gap-2">
                {c.detail && <span className="truncate text-xs text-[var(--muted)]">{c.detail}</span>}
                <Pill tone={healthTone(c.status)}>{c.status}</Pill>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-[var(--muted)]">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
