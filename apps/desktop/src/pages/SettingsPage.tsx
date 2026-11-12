import type { SystemInfo } from "@jack/shared-types";
import { useEffect, useState } from "react";
import type { ShortcutRow } from "../components/ShortcutsDialog";
import { Card } from "../components/ui";
import { ACCENTS, type Appearance } from "../lib/appearance";
import { useBackend } from "../lib/backend";

export function SettingsPage({
  appearance,
  onChange,
  shortcuts,
}: {
  appearance: Appearance;
  onChange: (a: Appearance) => void;
  shortcuts: ShortcutRow[];
}) {
  const { api, bridge } = useBackend();
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [autostart, setAutostart] = useState<boolean | null>(null);
  const [autostartError, setAutostartError] = useState<string | null>(null);

  useEffect(() => {
    api?.systemInfo().then(setInfo).catch(() => {});
  }, [api]);
  useEffect(() => {
    if (!bridge.autostart.supported) return;
    bridge.autostart.isEnabled().then(setAutostart).catch(() => setAutostart(null));
  }, [bridge]);

  async function toggleAutostart(on: boolean) {
    setAutostartError(null);
    try {
      await bridge.autostart.set(on);
      setAutostart(await bridge.autostart.isEnabled());
    } catch (e) {
      setAutostartError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Appearance">
        <fieldset className="space-y-4 text-sm">
          <legend className="sr-only">Theme</legend>
          <div className="flex gap-2" role="radiogroup" aria-label="Theme">
            {(["system", "dark", "light"] as const).map((t) => (
              <button
                key={t}
                type="button"
                role="radio"
                aria-checked={appearance.theme === t}
                onClick={() => onChange({ ...appearance, theme: t })}
                className={`rounded-lg border px-3 py-1.5 capitalize ${appearance.theme === t ? "border-[var(--accent)] text-[var(--accent)]" : "border-[var(--border)]"}`}
              >
                {t}
              </button>
            ))}
          </div>
          <div className="flex gap-2" role="radiogroup" aria-label="Accent colour">
            {ACCENTS.map((a) => (
              <button
                key={a.value}
                type="button"
                role="radio"
                aria-checked={appearance.accent === a.value}
                aria-label={a.name}
                onClick={() => onChange({ ...appearance, accent: a.value })}
                className={`h-8 w-8 rounded-full ring-offset-2 ring-offset-[var(--panel)] ${appearance.accent === a.value ? "ring-2 ring-[var(--text)]" : ""}`}
                style={{ background: a.value }}
              />
            ))}
          </div>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={appearance.compact} onChange={(e) => onChange({ ...appearance, compact: e.target.checked })} />
            Compact sidebar
          </label>
        </fieldset>
      </Card>

      <Card title="Startup">
        <div className="space-y-2 text-sm">
          <label className={`flex items-center justify-between gap-4 font-medium ${bridge.autostart.supported ? "" : "opacity-60"}`}>
            Start JACK when I sign in to Windows
            <input
              type="checkbox"
              role="switch"
              disabled={!bridge.autostart.supported || autostart === null}
              checked={autostart ?? false}
              onChange={(e) => void toggleAutostart(e.target.checked)}
              className="h-4 w-4 accent-[var(--accent)]"
            />
          </label>
          <p className="text-xs text-[var(--muted)]">
            {bridge.autostart.supported
              ? "JACK starts in the system tray without opening its window."
              : "Only available in the installed desktop app."}
          </p>
          {autostartError && <p role="alert" className="text-rose-500">{autostartError}</p>}
        </div>
      </Card>

      <Card title="Keyboard shortcuts">
        <table className="w-full text-sm">
          <tbody className="divide-y divide-[var(--border)]">
            {shortcuts.map((r) => (
              <tr key={r.keys}>
                <td className="py-1.5 pr-4">
                  <kbd className="rounded border border-[var(--border)] bg-[var(--bg)] px-1.5 py-0.5 font-mono text-xs">{r.keys}</kbd>
                </td>
                <td className="py-1.5">{r.action}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="Service">
        {!info ? (
          <p className="text-sm text-[var(--muted)]">Service not connected.</p>
        ) : (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-[var(--muted)]">Version</dt><dd>{info.app_version}</dd>
            <dt className="text-[var(--muted)]">Python</dt><dd>{info.python_version}</dd>
            <dt className="text-[var(--muted)]">Platform</dt><dd className="break-all">{info.platform}</dd>
            <dt className="text-[var(--muted)]">Database</dt><dd>{info.database_backend}</dd>
            <dt className="text-[var(--muted)]">Data directory</dt><dd className="break-all font-mono text-xs">{info.data_dir}</dd>
          </dl>
        )}
      </Card>
    </div>
  );
}
