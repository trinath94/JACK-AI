import type { ReactNode } from "react";

type Tone = "ok" | "warn" | "bad" | "muted" | "accent";

const TONE: Record<Tone, string> = {
  ok: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 ring-emerald-500/30",
  warn: "bg-amber-500/15 text-amber-700 dark:text-amber-300 ring-amber-500/30",
  bad: "bg-rose-500/15 text-rose-700 dark:text-rose-300 ring-rose-500/30",
  muted: "bg-slate-500/10 text-slate-600 dark:text-slate-300 ring-slate-500/20",
  accent: "bg-[var(--accent)]/15 text-[var(--accent)] ring-[var(--accent)]/30",
};

export function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${TONE[tone]}`}>
      {children}
    </span>
  );
}

export function Card({ title, action, children, className = "" }: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-5 shadow-sm ${className}`}>
      {(title || action) && (
        <header className="mb-4 flex items-center justify-between gap-3">
          {title && <h2 className="text-sm font-semibold tracking-wide text-[var(--muted)] uppercase">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function healthTone(s: string | undefined): Tone {
  if (s === "healthy" || s === "running" || s === "open" || s === "COMPLETED") return "ok";
  if (s === "degraded" || s === "starting" || s === "restarting" || s === "connecting") return "warn";
  if (s === "unhealthy" || s === "failed" || s === "FAILED") return "bad";
  return "muted";
}

export function taskTone(status: string): Tone {
  if (status === "COMPLETED") return "ok";
  if (["FAILED", "ROLLED_BACK"].includes(status)) return "bad";
  if (["CANCELLED"].includes(status)) return "muted";
  if (status.startsWith("WAITING") || status === "PAUSED" || status.endsWith("APPROVAL")) return "warn";
  return "accent";
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function Meter({ label, value, detail }: { label: string; value: number; detail?: string }) {
  const pct = Math.max(0, Math.min(100, value));
  const color = pct >= 90 ? "bg-rose-500" : pct >= 75 ? "bg-amber-500" : "bg-[var(--accent)]";
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="text-[var(--muted)]">{label}</span>
        <span className="tabular-nums">{detail ?? `${pct.toFixed(0)}%`}</span>
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-[var(--hover)]"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
      >
        <div className={`h-full rounded-full transition-[width] duration-500 ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function formatBytes(n: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function usd(v: string | null | undefined, digits = 2): string {
  if (v == null) return "—";
  const n = Number(v);
  // Tiny amounts (single requests) need more places to stay honest: $0.000148, not $0.0001.
  const max = n !== 0 && Math.abs(n) < 0.01 ? 6 : Math.max(digits, 4);
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: max })}`;
}
