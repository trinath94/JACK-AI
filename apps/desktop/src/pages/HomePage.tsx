import type { AuditEvent, DiscoveryResult, TaskDetail } from "@jack/shared-types";
import { CornerDownLeft, RotateCcw, ShieldCheck, X } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode, type RefObject } from "react";
import { PushToTalk } from "../components/PushToTalk";
import { Card, Meter, Pill, formatBytes, formatTime, healthTone, taskTone, usd } from "../components/ui";
import { VoiceOrb, type OrbState } from "../components/VoiceOrb";
import { ApiRequestError } from "../lib/api";
import { useBackend } from "../lib/backend";

const TERMINAL = new Set(["COMPLETED", "CANCELLED", "FAILED", "ROLLED_BACK"]);

// Integrations not yet available: shown with the milestone that delivers them, never with
// placeholder numbers.
const LATER_INTEGRATIONS = [
  { name: "AI agents", milestone: 7 },
  { name: "GitHub", milestone: 9 },
  { name: "Servers (SSH)", milestone: 10 },
  { name: "Deployments", milestone: 13 },
];

export function HomePage({ commandRef, shortcut, onOpenCommand }: {
  commandRef: RefObject<HTMLInputElement | null>; shortcut: string | null; onOpenCommand?: () => void;
}) {
  const { supervisor, socket, voice, voiceLevel, lastUtterance, lastReply, wokeAt, voiceError, clearVoiceError } = useBackend();
  const online = supervisor.state === "running" && socket === "open";
  const orb: OrbState = !online ? "offline" : (voice?.state ?? "idle");
  const woke = wokeAt !== null && Date.now() - wokeAt < 1500;

  return (
    <div className="grid gap-6 2xl:grid-cols-[1fr_400px] xl:grid-cols-[1fr_360px]">
      <div className="min-w-0 space-y-6">
        <Card className="flex flex-col items-center gap-5 py-8">
          <VoiceOrb state={orb} level={voiceLevel} woke={woke} />
          <PushToTalk shortcut={shortcut} />
          <VoiceChips />
          {(lastUtterance || lastReply) && voice?.state !== "listening" && (
            <div className="w-full max-w-xl space-y-1.5 rounded-xl bg-[var(--hover)] px-4 py-3 text-sm" data-testid="last-exchange">
              {lastUtterance?.transcript ? (
                <p><span className="font-semibold">You:</span> {lastUtterance.transcript}</p>
              ) : null}
              {lastReply && <p><span className="font-semibold text-[var(--accent)]">JACK:</span> {lastReply}</p>}
            </div>
          )}
          {voiceError && (
            <p role="alert" className="flex items-center gap-2 rounded-lg bg-rose-500/10 px-3 py-2 text-sm text-rose-600 dark:text-rose-300">
              {voiceError}
              <button type="button" onClick={clearVoiceError} aria-label="Dismiss voice error">
                <X className="h-3.5 w-3.5" />
              </button>
            </p>
          )}
          <CommandBox online={online} inputRef={commandRef} onOpenCommand={onOpenCommand} />
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
        <IntegrationsCard />
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
  const wake = !voice.settings.wake_word_enabled
    ? { tone: "muted" as const, text: 'Wake word "Jack": off' }
    : voice.state === "standby" || voice.state === "listening" || voice.state === "processing" || voice.state === "speaking"
      ? { tone: "ok" as const, text: 'Wake word "Jack": listening' }
      : { tone: "warn" as const, text: `Wake word: ${voice.capabilities.wake_word_detail ?? "unavailable"}` };
  return (
    <div className="flex flex-wrap justify-center gap-2">
      <Pill tone={mic.tone}>{mic.text}</Pill>
      <Pill tone={wake.tone}>{wake.text}</Pill>
      <Pill tone={voice.capabilities.speech_recognition ? "ok" : "warn"}>
        {voice.capabilities.speech_recognition
          ? `Speech recognition: ${voice.settings.asr_model}`
          : "Speech recognition: model not downloaded"}
      </Pill>
    </div>
  );
}

const OPEN_DISCOVERY = new Set(["choosing_category", "asking", "resolving_conflict", "awaiting_approval", "changing"]);

interface Exchange { sessionId: string; reply: string; options: string[]; open: boolean }

function CommandBox({ online, inputRef, onOpenCommand }: {
  online: boolean; inputRef: RefObject<HTMLInputElement | null>; onOpenCommand?: () => void;
}) {
  const { api, discoveryTick } = useBackend();
  const [command, setCommand] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ex, setEx] = useState<Exchange | null>(null);
  const [dismissed, setDismissed] = useState<string | null>(null);

  // Show the conversation JACK is waiting on (also after navigating away and back), and keep the
  // question current when it moves on elsewhere (voice, Command Centre).
  useEffect(() => {
    if (!api) return;
    let live = true;
    const pick = ex ? Promise.resolve(ex.sessionId)
      : api.discoverySessions(true).then((l) => l.find((s) => s.id !== dismissed)?.id ?? null);
    pick.then((id) => (id ? api.discoverySession(id) : null)).then((s) => {
      if (!s) return;
      const last = [...(s.turns ?? [])].reverse().find((t) => t.role === "jack");
      if (!live || !last) return;
      const q = s.question;
      const options = q?.kind === "slot" && q.input === "bool" ? ["Yes", "No"] : (q?.options ?? []).map((o) => o.label);
      setEx({ sessionId: s.id, reply: last.text, options, open: OPEN_DISCOVERY.has(s.status) });
    }).catch(() => {});
    return () => {
      live = false;
    };
  }, [api, discoveryTick, dismissed]);

  async function send(text: string) {
    if (!api || !text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r: DiscoveryResult = await api.discoveryMessage(text.trim(), ex?.open ? ex.sessionId : undefined);
      setEx({ sessionId: r.session.id, reply: r.reply.text, options: r.reply.options, open: r.reply.expects_answer });
      setCommand("");
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "Could not send that to JACK");
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void send(command);
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
          placeholder={!online ? "Waiting for JACK service…" : ex?.open ? "Answer JACK…" : "Type a command for JACK…  (Ctrl+K)"}
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
      {ex ? (
        <div className="w-full max-w-2xl space-y-2 rounded-xl bg-[var(--hover)] px-4 py-3 text-sm" data-testid="discovery-exchange">
          <p><span className="font-semibold text-[var(--accent)]">JACK:</span> {ex.reply}</p>
          {ex.open && ex.options.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {ex.options.map((o) => (
                <button key={o} type="button" disabled={busy} onClick={() => void send(o)}
                  className="rounded-full border border-[var(--border)] bg-[var(--panel)] px-3 py-1 text-xs hover:bg-[var(--hover)]">{o}</button>
              ))}
            </div>
          )}
          <div className="flex gap-3 text-xs">
            {onOpenCommand && <button type="button" onClick={onOpenCommand} className="text-[var(--accent)] hover:underline">Open in Command Centre</button>}
            {ex.open && <button type="button" onClick={() => { setDismissed(ex.sessionId); setEx(null); }} className="text-[var(--muted)] hover:underline">Start a new request instead</button>}
          </div>
        </div>
      ) : (
        <p className="max-w-2xl text-center text-xs text-[var(--muted)]">
          JACK asks what it needs to know, one question at a time, then writes a specification. Planning and building arrive in later milestones.
        </p>
      )}
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

function IntegrationsCard() {
  const { ai } = useBackend();
  const claude = !ai
    ? { tone: "muted" as const, text: "unknown" }
    : ai.anthropic.configured
      ? ai.anthropic.last_test && !ai.anthropic.last_test.ok
        ? { tone: "bad" as const, text: `error: ${ai.anthropic.last_test.error_code}` }
        : { tone: "ok" as const, text: ai.anthropic.settings.model }
      : ai.claude_code.settings.enabled
        ? { tone: "ok" as const, text: "Claude Code" }
        : { tone: "warn" as const, text: "not configured" };
  return (
    <Card title="Integrations">
      <ul className="space-y-2 text-sm" aria-label="Integrations">
        <li className="flex items-center justify-between gap-3">
          <span className="truncate">Claude</span>
          <Pill tone={claude.tone}>{claude.text}</Pill>
        </li>
        <li className="flex items-center justify-between gap-3">
          <span className="truncate">API spend this month</span>
          <span className="tabular-nums" data-testid="home-api-spend">
            {ai ? usd(ai.month.api.cost_usd) : "—"}
            {ai?.month.monthly_limit_usd ? <span className="text-xs text-[var(--muted)]"> / {usd(ai.month.monthly_limit_usd)}</span> : null}
          </span>
        </li>
        {LATER_INTEGRATIONS.map((i) => (
          <li key={i.name} className="flex items-center justify-between gap-3">
            <span className="truncate">{i.name}</span>
            <Pill tone="muted">Milestone {i.milestone}</Pill>
          </li>
        ))}
      </ul>
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
