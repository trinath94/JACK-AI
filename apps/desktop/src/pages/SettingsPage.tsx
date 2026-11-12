import type { SystemInfo } from "@jack/shared-types";
import { useEffect, useState } from "react";
import { Card } from "../components/ui";
import { useBackend } from "../lib/backend";
import { ACCENTS, type Appearance } from "../lib/appearance";

export function SettingsPage({
  appearance,
  onChange,
}: {
  appearance: Appearance;
  onChange: (a: Appearance) => void;
}) {
  const { api } = useBackend();
  const [info, setInfo] = useState<SystemInfo | null>(null);
  useEffect(() => {
    api?.systemInfo().then(setInfo).catch(() => {});
  }, [api]);

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
            <input
              type="checkbox"
              checked={appearance.compact}
              onChange={(e) => onChange({ ...appearance, compact: e.target.checked })}
            />
            Compact sidebar
          </label>
        </fieldset>
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
