import type { TaskDetail } from "@jack/shared-types";
import { Pause, Play, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Card, Pill, formatTime, taskTone } from "../components/ui";
import { ApiRequestError } from "../lib/api";
import { useBackend } from "../lib/backend";

const HOLD = new Set(["PAUSED", "WAITING_FOR_INFORMATION", "WAITING_FOR_APPROVAL"]);
const TERMINAL = new Set(["COMPLETED", "CANCELLED", "FAILED", "ROLLED_BACK"]);

export function TasksPage() {
  const { tasks, api } = useBackend();
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const current = tasks.find((t) => t.id === selected);

  useEffect(() => {
    if (!api || !selected) return setDetail(null);
    let live = true;
    api.getTask(selected).then((d) => live && setDetail(d)).catch(() => {});
    return () => {
      live = false;
    };
  }, [api, selected, current?.updated_at]);

  async function act(action: "pause" | "resume" | "cancel") {
    if (!api || !selected) return;
    setError(null);
    try {
      await api.taskAction(selected, action);
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : "Action failed");
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
      <Card title={`Tasks (${tasks.length})`}>
        {tasks.length === 0 ? (
          <p className="text-sm text-[var(--muted)]">No tasks yet. Give JACK a command on the Home page.</p>
        ) : (
          <ul className="space-y-1">
            {tasks.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => setSelected(t.id)}
                  className={`flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--hover)] ${
                    selected === t.id ? "bg-[var(--hover)]" : ""
                  }`}
                >
                  <span className="truncate">{t.title}</span>
                  <Pill tone={taskTone(t.status)}>{t.status}</Pill>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Task detail">
        {!detail ? (
          <p className="text-sm text-[var(--muted)]">Select a task.</p>
        ) : (
          <div className="space-y-4 text-sm">
            <div>
              <p className="text-xs text-[var(--muted)]">Task ID</p>
              <p className="font-mono text-xs">{detail.id}</p>
            </div>
            <div>
              <p className="text-xs text-[var(--muted)]">Command</p>
              <p className="whitespace-pre-wrap">{detail.command_text}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {!TERMINAL.has(detail.status) && !HOLD.has(detail.status) && (
                <ActionButton onClick={() => void act("pause")} icon={<Pause className="h-3.5 w-3.5" />}>Pause</ActionButton>
              )}
              {HOLD.has(detail.status) && (
                <ActionButton onClick={() => void act("resume")} icon={<Play className="h-3.5 w-3.5" />}>Resume</ActionButton>
              )}
              {!TERMINAL.has(detail.status) && (
                <ActionButton onClick={() => void act("cancel")} icon={<X className="h-3.5 w-3.5" />}>Cancel</ActionButton>
              )}
            </div>
            {error && <p role="alert" className="text-rose-500">{error}</p>}
            <div>
              <p className="mb-2 text-xs text-[var(--muted)]">Timeline</p>
              <ol className="space-y-2 border-l border-[var(--border)] pl-4">
                {detail.events.map((e) => (
                  <li key={e.seq}>
                    <Pill tone={taskTone(e.to_status)}>{e.to_status}</Pill>
                    <span className="ml-2 text-xs text-[var(--muted)]">
                      {formatTime(e.occurred_at)} · {e.actor}{e.reason ? ` · ${e.reason}` : ""}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

function ActionButton({ onClick, icon, children }: { onClick: () => void; icon: React.ReactNode; children: React.ReactNode }) {
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
