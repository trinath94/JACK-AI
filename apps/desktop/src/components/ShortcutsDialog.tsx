import { useEffect, useRef } from "react";

export interface ShortcutRow {
  keys: string;
  action: string;
}

export function ShortcutsDialog({ rows, onClose }: { rows: ShortcutRow[]; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-black/50 p-4" onMouseDown={onClose}>
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard shortcuts"
        onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-6 shadow-2xl outline-none"
      >
        <h2 className="mb-4 text-lg font-semibold">Keyboard shortcuts</h2>
        <table className="w-full text-sm">
          <tbody className="divide-y divide-[var(--border)]">
            {rows.map((r) => (
              <tr key={r.keys}>
                <td className="py-2 pr-4">
                  <kbd className="rounded border border-[var(--border)] bg-[var(--bg)] px-1.5 py-0.5 font-mono text-xs">{r.keys}</kbd>
                </td>
                <td className="py-2">{r.action}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" onClick={onClose} className="mt-5 w-full rounded-lg border border-[var(--border)] py-2 text-sm hover:bg-[var(--hover)]">
          Close
        </button>
      </div>
    </div>
  );
}
