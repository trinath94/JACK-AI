import { CornerDownLeft, MicOff, RotateCcw } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Card, Pill, formatTime, healthTone, taskTone } from "../components/ui";
import { VoiceOrb } from "../components/VoiceOrb";
import { ApiRequestError } from "../lib/api";
import { useBackend } from "../lib/backend";

export function HomePage() {
  const { supervisor, socket, health, tasks, api, restart } = useBackend();
  const [command, setCommand] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const online = supervisor.state === "running" && socket === "open";

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
    <div className="grid gap-6 xl:grid-cols-[1fr_380px]">
      <div className="space-y-6">
        <Card className="flex flex-col items-center gap-6 py-10">
          <VoiceOrb state={online ? "idle" : "offline"} />
          <div className="flex flex-wrap justify-center gap-2">
            <Pill tone="muted">
              <MicOff className="h-3 w-3" aria-hidden /> Microphone: not available until Milestone 3
            </Pill>
            <Pill tone="muted">Wake word "Jack": not available until Milestone 3</Pill>
          </div>
          <form onSubmit={submit} className="flex w-full max-w-2xl gap-2">
            <label htmlFor="command" className="sr-only">Command</label>
            <input
              id="command"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder={online ? "Type a command for JACK…" : "Waiting for JACK service…"}
              disabled={!online || busy}
              maxLength={4000}
              className="flex-1 rounded-xl border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-[var(--accent)] disabled:opacity-60"
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
            Commands are recorded as durable tasks. Planning and execution by JACK's agents arrive in
            Milestones 5–7; until then tasks stay in <code>RECEIVED</code>.
          </p>
          {error && <p role="alert" className="text-sm text-rose-500">{error}</p>}
        </Card>

        <Card title="Recent tasks">
          {tasks.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">No tasks yet.</p>
          ) : (
            <ul className="divide-y divide-[var(--border)]" aria-label="Recent tasks">
              {tasks.slice(0, 8).map((t) => (
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
      </div>

      <div className="space-y-6">
        <Card
          title="JACK service"
          action={
            <button
              type="button"
              onClick={() => void restart()}
              className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-[var(--muted)] hover:bg-[var(--hover)]"
            >
              <RotateCcw className="h-3 w-3" aria-hidden /> Restart
            </button>
          }
        >
          <dl className="space-y-3 text-sm">
            <Row label="Supervisor"><Pill tone={healthTone(supervisor.state)}>{supervisor.state}</Pill></Row>
            <Row label="Live connection"><Pill tone={healthTone(socket)}>{socket}</Pill></Row>
            <Row label="Overall health"><Pill tone={healthTone(health?.status)}>{health?.status ?? "unknown"}</Pill></Row>
            <Row label="Restarts">{supervisor.restarts}</Row>
            {supervisor.pid !== null && <Row label="PID">{supervisor.pid}</Row>}
          </dl>
          {supervisor.lastError && (
            <p className="mt-3 rounded-lg bg-rose-500/10 p-2 text-xs text-rose-600 dark:text-rose-300">
              {supervisor.lastError}
            </p>
          )}
        </Card>

        <Card title="Components">
          {!health ? (
            <p className="text-sm text-[var(--muted)]">No health data yet.</p>
          ) : (
            <ul className="space-y-2" aria-label="Component health">
              {health.components.map((c) => (
                <li key={c.name} className="flex items-center justify-between text-sm">
                  <span className="capitalize">{c.name}</span>
                  <span className="flex items-center gap-2">
                    {c.detail && <span className="text-xs text-[var(--muted)]">{c.detail}</span>}
                    <Pill tone={healthTone(c.status)}>{c.status}</Pill>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-[var(--muted)]">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
