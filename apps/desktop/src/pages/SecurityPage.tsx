import type { AuditEvent } from "@jack/shared-types";
import { RefreshCw, ShieldCheck, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Card, Pill, formatTime } from "../components/ui";
import { useBackend } from "../lib/backend";

export function SecurityPage() {
  const { api } = useBackend();
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [verify, setVerify] = useState<{ valid: boolean; checked: number; first_invalid_seq: number | null } | null>(null);

  const load = useCallback(async () => {
    if (!api) return;
    const [list, v] = await Promise.all([api.audit(100), api.verifyAudit()]);
    setEvents(list.items);
    setTotal(list.total);
    setVerify(v);
  }, [api]);

  useEffect(() => {
    void load().catch(() => {});
  }, [load]);

  return (
    <div className="space-y-6">
      <Card
        title="Audit chain"
        action={
          <button type="button" onClick={() => void load()} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs hover:bg-[var(--hover)]">
            <RefreshCw className="h-3 w-3" aria-hidden /> Refresh
          </button>
        }
      >
        {!verify ? (
          <p className="text-sm text-[var(--muted)]">Not verified yet.</p>
        ) : verify.valid ? (
          <p className="flex items-center gap-2 text-sm text-emerald-600 dark:text-emerald-300">
            <ShieldCheck className="h-4 w-4" aria-hidden /> Chain intact — {verify.checked} events verified.
          </p>
        ) : (
          <p role="alert" className="flex items-center gap-2 text-sm text-rose-600 dark:text-rose-300">
            <ShieldAlert className="h-4 w-4" aria-hidden /> Tampering detected at event #{verify.first_invalid_seq}.
          </p>
        )}
      </Card>
      <Card title={`Audit events (${total})`}>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-[var(--muted)]">
              <tr>
                <th className="py-2 pr-4">#</th>
                <th className="py-2 pr-4">Time</th>
                <th className="py-2 pr-4">Action</th>
                <th className="py-2 pr-4">Target</th>
                <th className="py-2 pr-4">Outcome</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {events.map((e) => (
                <tr key={e.seq}>
                  <td className="py-2 pr-4 font-mono text-xs">{e.seq}</td>
                  <td className="py-2 pr-4 text-xs">{formatTime(e.occurred_at)}</td>
                  <td className="py-2 pr-4">{e.action}</td>
                  <td className="py-2 pr-4 font-mono text-xs">{e.target ?? "—"}</td>
                  <td className="py-2 pr-4">
                    <Pill tone={e.outcome === "denied" ? "bad" : e.outcome === "error" ? "warn" : "muted"}>{e.outcome}</Pill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
