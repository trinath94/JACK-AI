import type { Approval } from "@jack/shared-types";
import { Check, ShieldCheck, X } from "lucide-react";
import { useEffect, useState } from "react";
import { ApiRequestError } from "../lib/api";
import { useBackend } from "../lib/backend";
import { Pill, formatTime } from "./ui";

const RISK = { low: "muted", medium: "warn", high: "bad" } as const;

/** Pending approvals, each bound to one action, one target and an expiry (M6). */
export function ApprovalList({ taskId, emptyText }: { taskId?: string; emptyText?: string }) {
  const { api, executionTick, discoveryTick } = useBackend();
  const [items, setItems] = useState<Approval[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!api) return;
    let live = true;
    api.approvals("pending").then((l) => live && setItems(taskId ? l.filter((a) => a.task_id === taskId) : l)).catch(() => {});
    return () => {
      live = false;
    };
  }, [api, taskId, executionTick, discoveryTick]);

  async function decide(a: Approval, decision: "approve" | "deny") {
    if (!api || !a.nonce) return;
    setError(null);
    try {
      await api.decideApproval(a.id, decision, a.nonce);
      setItems((l) => l.filter((x) => x.id !== a.id));
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : "Could not record the decision");
    }
  }

  if (items.length === 0) {
    return (
      <p className="flex items-start gap-2 text-sm text-[var(--muted)]">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        {emptyText ?? "No pending approvals. When a task needs your decision, it appears here, tied to one action, one target and an expiry."}
      </p>
    );
  }
  return (
    <ul className="space-y-3" aria-label="Pending approvals">
      {items.map((a) => (
        <li key={a.id} className="rounded-xl border border-[var(--border)] p-3 text-sm">
          <div className="flex items-start justify-between gap-2">
            <p className="font-medium">{a.summary}</p>
            <Pill tone={RISK[a.risk]}>{a.risk} risk</Pill>
          </div>
          <p className="mt-1 font-mono text-xs text-[var(--muted)]">{a.action} · {a.target}</p>
          <p className="text-xs text-[var(--muted)]">Expires {formatTime(a.expires_at)}</p>
          <div className="mt-2 flex gap-2">
            <button type="button" onClick={() => void decide(a, "approve")} className="inline-flex items-center gap-1 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-white">
              <Check className="h-3.5 w-3.5" aria-hidden /> Approve
            </button>
            <button type="button" onClick={() => void decide(a, "deny")} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--hover)]">
              <X className="h-3.5 w-3.5" aria-hidden /> Deny
            </button>
          </div>
        </li>
      ))}
      {error && <li role="alert" className="text-sm text-rose-500">{error}</li>}
    </ul>
  );
}
