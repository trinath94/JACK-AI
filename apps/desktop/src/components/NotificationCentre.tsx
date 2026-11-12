import type { Notification } from "@jack/shared-types";
import { AlertTriangle, Bell, CheckCircle2, Info, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useBackend } from "../lib/backend";
import { formatTime } from "./ui";

const ICON = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: XCircle,
} as const;

const TONE = {
  info: "text-sky-500",
  success: "text-emerald-500",
  warning: "text-amber-500",
  error: "text-rose-500",
} as const;

export function NotificationCentre() {
  const { notifications, unread, markRead, markAllRead } = useBackend();
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const onClick = (e: MouseEvent) => {
      if (panel.current && !panel.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  return (
    <div className="relative" ref={panel}>
      <button
        type="button"
        aria-label={`Notifications${unread ? ` (${unread} unread)` : ""}`}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="relative rounded-lg p-2 hover:bg-[var(--hover)]"
      >
        <Bell className="h-5 w-5" aria-hidden />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-rose-500 px-1 text-[10px] font-bold text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Notification centre"
          className="absolute right-0 z-20 mt-2 w-96 max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--panel)] shadow-xl"
        >
          <header className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
            <h2 className="text-sm font-semibold">Notifications</h2>
            <button
              type="button"
              disabled={unread === 0}
              onClick={() => void markAllRead()}
              className="text-xs text-[var(--accent)] disabled:opacity-40"
            >
              Mark all read
            </button>
          </header>
          {notifications.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-[var(--muted)]">You're all caught up.</p>
          ) : (
            <ul className="max-h-96 divide-y divide-[var(--border)] overflow-y-auto" aria-label="Notifications">
              {notifications.map((n) => (
                <Item key={n.id} n={n} onRead={() => void markRead(n.id)} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function Item({ n, onRead }: { n: Notification; onRead: () => void }) {
  const Icon = ICON[n.level];
  return (
    <li className={`flex gap-3 px-4 py-3 text-sm ${n.read_at ? "opacity-60" : ""}`}>
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${TONE[n.level]}`} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{n.title}</p>
        {n.body && <p className="truncate text-xs text-[var(--muted)]">{n.body}</p>}
        <p className="mt-0.5 text-[11px] text-[var(--muted)]">{formatTime(n.created_at)}</p>
      </div>
      {!n.read_at && (
        <button type="button" onClick={onRead} className="self-start text-xs text-[var(--accent)]" aria-label={`Mark "${n.title}" read`}>
          Mark read
        </button>
      )}
    </li>
  );
}
