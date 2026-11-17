import type { TaskDetail, TaskExecution, TaskStep } from "@jack/shared-types";
import { CheckCircle2, Circle, FileText, Loader2, Pause, PauseCircle, Play, RotateCcw, ShieldAlert, X, XCircle } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { ApprovalList } from "../components/ApprovalList";
import { Card, Pill, formatBytes, formatTime, taskTone } from "../components/ui";
import { ApiRequestError } from "../lib/api";
import { useBackend } from "../lib/backend";

const HOLD = new Set(["PAUSED", "WAITING_FOR_INFORMATION", "WAITING_FOR_APPROVAL"]);
const TERMINAL = new Set(["COMPLETED", "CANCELLED", "FAILED", "ROLLED_BACK"]);

const STEP: Record<TaskStep["status"], { label: string; tone: "ok" | "warn" | "bad" | "muted" | "accent"; icon: ReactNode }> = {
  pending: { label: "to do", tone: "muted", icon: <Circle className="h-4 w-4 text-[var(--muted)]" aria-hidden /> },
  running: { label: "running", tone: "accent", icon: <Loader2 className="h-4 w-4 animate-spin text-[var(--accent)]" aria-hidden /> },
  done: { label: "done", tone: "ok", icon: <CheckCircle2 className="h-4 w-4 text-emerald-500" aria-hidden /> },
  blocked: { label: "waiting", tone: "warn", icon: <PauseCircle className="h-4 w-4 text-amber-500" aria-hidden /> },
  waiting_approval: { label: "needs approval", tone: "warn", icon: <ShieldAlert className="h-4 w-4 text-amber-500" aria-hidden /> },
  needs_review: { label: "needs review", tone: "warn", icon: <ShieldAlert className="h-4 w-4 text-amber-500" aria-hidden /> },
  skipped: { label: "skipped", tone: "muted", icon: <Circle className="h-4 w-4 text-[var(--muted)]" aria-hidden /> },
  failed: { label: "failed", tone: "bad", icon: <XCircle className="h-4 w-4 text-rose-500" aria-hidden /> },
};

export function TasksPage() {
  const { tasks, api, executionTick } = useBackend();
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [exec, setExec] = useState<TaskExecution | null>(null);
  const [viewing, setViewing] = useState<{ name: string; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const id = selected ?? tasks[0]?.id ?? null;
  const current = tasks.find((t) => t.id === id);

  useEffect(() => {
    if (!api || !id) {
      setDetail(null);
      setExec(null);
      return;
    }
    let live = true;
    api.getTask(id).then((d) => live && setDetail(d)).catch(() => {});
    api.taskExecution(id).then((e) => live && setExec(e)).catch(() => live && setExec(null));
    return () => {
      live = false;
    };
  }, [api, id, current?.updated_at, executionTick]);

  async function act(action: "pause" | "resume" | "cancel" | "retry") {
    if (!api || !id) return;
    setError(null);
    try {
      if (action === "retry") await api.retryTask(id);
      else await api.taskAction(id, action);
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : "Action failed");
    }
  }

  async function open(artifactId: string, name: string) {
    if (!api || !id) return;
    try {
      setViewing({ name, text: await api.artifactText(id, artifactId) });
    } catch {
      setError("Could not open that file");
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[22rem_1fr]">
      <Card title={`Tasks (${tasks.length})`}>
        {tasks.length === 0 ? (
          <p className="text-sm text-[var(--muted)]">No tasks yet. Give JACK a command on the Home page.</p>
        ) : (
          <ul className="space-y-1" aria-label="Tasks">
            {tasks.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => setSelected(t.id)}
                  aria-current={id === t.id}
                  className={`flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--hover)] ${id === t.id ? "bg-[var(--hover)]" : ""}`}
                >
                  <span className="truncate">{t.title}</span>
                  <Pill tone={taskTone(t.status)}>{t.status}</Pill>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="space-y-6">
        <Card title="Task" action={detail && <Pill tone={taskTone(detail.status)}>{detail.status}</Pill>}>
          {!detail ? (
            <p className="text-sm text-[var(--muted)]">Select a task.</p>
          ) : (
            <div className="space-y-4 text-sm">
              <div>
                <h2 className="text-lg font-semibold" data-testid="task-title">{detail.title}</h2>
                <p className="text-[var(--muted)]">“{detail.command_text}”</p>
                <p className="mt-1 font-mono text-xs text-[var(--muted)]">{detail.id}</p>
              </div>
              {detail.status_reason && !TERMINAL.has(detail.status) && (
                <p className="rounded-lg bg-[var(--hover)] px-3 py-2" data-testid="status-reason">{detail.status_reason}</p>
              )}
              {exec?.summary && detail.status === "COMPLETED" && (
                <p className="flex items-center gap-2 text-emerald-600 dark:text-emerald-300"><CheckCircle2 className="h-4 w-4" aria-hidden /> {exec.summary}</p>
              )}
              <div className="flex flex-wrap gap-2">
                {!TERMINAL.has(detail.status) && !HOLD.has(detail.status) && (
                  <ActionButton onClick={() => void act("pause")} icon={<Pause className="h-3.5 w-3.5" />}>Pause</ActionButton>
                )}
                {HOLD.has(detail.status) && (
                  <ActionButton onClick={() => void act("resume")} icon={<Play className="h-3.5 w-3.5" />}>Resume</ActionButton>
                )}
                {detail.status === "FAILED" && exec && exec.steps.length > 0 && (
                  <ActionButton onClick={() => void act("retry")} icon={<RotateCcw className="h-3.5 w-3.5" />}>Retry from where it stopped</ActionButton>
                )}
                {!TERMINAL.has(detail.status) && (
                  <ActionButton onClick={() => void act("cancel")} icon={<X className="h-3.5 w-3.5" />}>Cancel</ActionButton>
                )}
              </div>
              {error && <p role="alert" className="text-rose-500">{error}</p>}
            </div>
          )}
        </Card>

        {exec && exec.approvals.some((a) => a.status === "pending") && (
          <Card title="Needs your approval">
            <ApprovalList taskId={exec.task_id} />
          </Card>
        )}

        {exec && exec.steps.length > 0 && (
          <Card title="Steps">
            <ol className="space-y-2" aria-label="Steps">
              {exec.steps.map((s) => (
                <li key={s.id} className="flex items-start gap-3 text-sm" data-testid={`step-${s.key}`}>
                  <span className="mt-0.5">{STEP[s.status].icon}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{s.title}</span>
                      <Pill tone={STEP[s.status].tone}>{STEP[s.status].label}</Pill>
                      {s.needs_approval && <Pill tone="muted">approval</Pill>}
                    </div>
                    <p className="text-xs text-[var(--muted)]">
                      {s.agent_role}
                      {s.attempts > 1 ? ` · ${s.attempts} attempts` : ""}
                      {!s.idempotent ? " · not repeated automatically" : ""}
                    </p>
                    {s.blocked_reason && <p className="text-xs text-amber-600 dark:text-amber-300">{s.blocked_reason}</p>}
                    {s.error && s.status !== "done" && <p className="text-xs text-rose-500">{s.error}</p>}
                  </div>
                </li>
              ))}
            </ol>
          </Card>
        )}

        {exec && exec.artifacts.length > 0 && (
          <Card title="Files JACK produced">
            <ul className="space-y-1 text-sm" aria-label="Artifacts">
              {exec.artifacts.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-2">
                  <button type="button" onClick={() => void open(a.id, a.name)} className="inline-flex items-center gap-2 text-[var(--accent)] hover:underline">
                    <FileText className="h-4 w-4" aria-hidden /> {a.name}
                  </button>
                  <span className="text-xs text-[var(--muted)]">{formatBytes(a.size_bytes)} · {formatTime(a.created_at)}</span>
                </li>
              ))}
            </ul>
            {viewing && (
              <div className="mt-3 rounded-xl border border-[var(--border)]">
                <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-2 text-xs">
                  <span className="font-mono">{viewing.name}</span>
                  <button type="button" onClick={() => setViewing(null)} aria-label="Close file"><X className="h-3.5 w-3.5" /></button>
                </div>
                <pre className="max-h-96 overflow-auto whitespace-pre-wrap p-3 text-xs" data-testid="artifact-text">{viewing.text}</pre>
              </div>
            )}
          </Card>
        )}

        {detail && (
          <Card title="Timeline">
            <ol className="space-y-2 border-l border-[var(--border)] pl-4 text-sm">
              {detail.events.map((e) => (
                <li key={e.seq}>
                  <Pill tone={taskTone(e.to_status)}>{e.to_status}</Pill>
                  <span className="ml-2 text-xs text-[var(--muted)]">
                    {formatTime(e.occurred_at)} · {e.actor}{e.reason ? ` · ${e.reason}` : ""}
                  </span>
                </li>
              ))}
            </ol>
          </Card>
        )}
      </div>
    </div>
  );
}

function ActionButton({ onClick, icon, children }: { onClick: () => void; icon: ReactNode; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium hover:bg-[var(--hover)]"
    >
      {icon}
      {children}
    </button>
  );
}
