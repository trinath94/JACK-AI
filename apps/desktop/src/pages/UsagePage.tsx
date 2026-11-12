import type { AICompletion, AIEffort, AIModel, AIProviderId, AISettingsPatch, UsageRecordRow } from "@jack/shared-types";
import { CheckCircle2, KeyRound, Lock, RefreshCw, Send, ShieldAlert, Trash2, XCircle } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Card, Meter, Pill, formatTime, usd } from "../components/ui";
import { ApiRequestError } from "../lib/api";
import { useBackend } from "../lib/backend";

const EFFORTS: AIEffort[] = ["low", "medium", "high", "xhigh", "max"];
const FALLBACK_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2"];

const tokens = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n));

export function UsagePage() {
  const { api, ai, refreshAI, activity } = useBackend();
  const [error, setError] = useState<string | null>(null);
  const [records, setRecords] = useState<UsageRecordRow[]>([]);

  useEffect(() => {
    if (!api) return;
    const t = setTimeout(() => api.aiUsageRecords(15).then((r) => setRecords(r.items)).catch(() => {}), 200);
    return () => clearTimeout(t);
  }, [api, activity]);

  const run = useCallback(
    async (fn: () => Promise<unknown>) => {
      setError(null);
      try {
        await fn();
      } catch (e) {
        setError(e instanceof ApiRequestError ? e.message : "Action failed");
      } finally {
        void refreshAI().catch(() => {});
      }
    },
    [refreshAI],
  );
  const patch = (p: AISettingsPatch) => run(() => api!.updateAISettings(p));

  if (!api || !ai) {
    return <Card><p className="text-sm text-[var(--muted)]">AI settings are available once the JACK service is running.</p></Card>;
  }
  const m = ai.month;
  const limitPct = m.limit_used_pct;

  return (
    <div className="space-y-6">
      {error && <p role="alert" className="rounded-lg bg-rose-500/10 px-3 py-2 text-sm text-rose-600 dark:text-rose-300">{error}</p>}
      <div className="grid gap-6 xl:grid-cols-2">
        <Card title={`This month (${m.month})`}>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <p className="text-xs text-[var(--muted)]">Anthropic API spend (estimated)</p>
              <p className="text-2xl font-semibold tabular-nums" data-testid="api-spend">{usd(m.api.cost_usd)}</p>
              <p className="text-xs text-[var(--muted)]">
                {m.api.requests} {m.api.requests === 1 ? "request" : "requests"} · {tokens(m.api.input_tokens)} in · {tokens(m.api.output_tokens)} out
                {m.api.failed ? ` · ${m.api.failed} failed` : ""}
              </p>
              {m.api.unpriced_requests > 0 && <p className="text-xs text-amber-600 dark:text-amber-300">{m.api.unpriced_requests} request(s) on models without a known price are not included.</p>}
            </div>
            <div>
              <p className="text-xs text-[var(--muted)]">Claude Code (reported by Claude Code)</p>
              <p className="text-2xl font-semibold tabular-nums" data-testid="cc-usage">{usd(m.claude_code.cost_usd)}</p>
              <p className="text-xs text-[var(--muted)]">
                {m.claude_code.requests} {m.claude_code.requests === 1 ? "request" : "requests"}. May be covered by your Claude plan rather than billed as API usage; never counted toward API spend or limits.
              </p>
            </div>
          </div>
          {m.monthly_limit_usd && (
            <div className="mt-4">
              <Meter label={`Monthly limit ${usd(m.monthly_limit_usd)}`} value={limitPct ?? 0} detail={`${limitPct ?? 0}% used`} />
            </div>
          )}
          {m.by_model.length > 0 && (
            <table className="mt-4 w-full text-sm" aria-label="Usage by model">
              <thead className="text-xs text-[var(--muted)]">
                <tr><th className="py-1 text-left">Model</th><th className="text-right">In</th><th className="text-right">Out</th><th className="text-right">Cost</th></tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {m.by_model.map((r) => (
                  <tr key={`${r.billing_kind}:${r.model}`}>
                    <td className="py-1.5 font-mono text-xs">{r.model}{r.billing_kind === "claude_code" ? " (Claude Code)" : ""}</td>
                    <td className="text-right tabular-nums">{tokens(r.input_tokens)}</td>
                    <td className="text-right tabular-nums">{tokens(r.output_tokens)}</td>
                    <td className="text-right tabular-nums">{usd(r.cost_usd, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="mt-3 text-[11px] text-[var(--muted)]">
            Estimates use Anthropic list prices as of {ai.prices_as_of}. Your Anthropic invoice is authoritative.
          </p>
        </Card>

        <Card title="Spending limits">
          <LimitsForm limits={ai.limits} onSave={(l) => void patch({ limits: l })} />
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Anthropic API" action={<StoreBadge kind={ai.credential_store.kind} secure={ai.credential_store.secure} available={ai.credential_store.available} />}>
          <AnthropicSection run={run} patch={patch} />
        </Card>
        <Card title="Claude Code">
          <ClaudeCodeSection run={run} patch={patch} />
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Routing and fallback">
          <div className="space-y-4 text-sm">
            <Select id="route-reasoning" label="Reasoning and conversation" value={ai.routing.reasoning} onChange={(v) => void patch({ routing: { reasoning: v as AIProviderId } })}
              options={[["anthropic", "Anthropic API"], ["claude_code", "Claude Code"]]} />
            <Select id="route-coding" label="Coding work (from Milestone 11)" value={ai.routing.coding} onChange={(v) => void patch({ routing: { coding: v as AIProviderId } })}
              options={[["claude_code", "Claude Code"], ["anthropic", "Anthropic API"]]} />
            <Toggle label="Fall back to the other provider when one fails" checked={ai.fallback.enabled} onChange={(v) => void patch({ fallback: { enabled: v } })}
              hint="Off by default. Switching provider can change cost and how your data is handled; every fallback is logged on the Security page and announced in notifications." />
          </div>
        </Card>
        <Card title="Test console">
          <TestConsole />
        </Card>
      </div>

      <Card title="Recent requests">
        {records.length === 0 ? (
          <p className="text-sm text-[var(--muted)]">No AI requests yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm" aria-label="Recent AI requests">
              <thead className="text-xs text-[var(--muted)]">
                <tr><th className="py-2 pr-3">Time</th><th className="pr-3">Provider</th><th className="pr-3">Model</th><th className="pr-3">Purpose</th><th className="pr-3 text-right">Tokens in/out</th><th className="pr-3 text-right">Cost</th><th>Result</th></tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {records.map((r) => (
                  <tr key={r.id}>
                    <td className="py-2 pr-3 text-xs">{formatTime(r.occurred_at)}</td>
                    <td className="pr-3 text-xs">{r.provider === "claude_code" ? "Claude Code" : "Anthropic API"}</td>
                    <td className="pr-3 font-mono text-xs">{r.model}</td>
                    <td className="pr-3 text-xs">{r.purpose.replace("_", " ")}</td>
                    <td className="pr-3 text-right text-xs tabular-nums">{tokens(r.input_tokens)} / {tokens(r.output_tokens)}</td>
                    <td className="pr-3 text-right text-xs tabular-nums">{usd(r.cost_usd, 4)}{r.cost_source === "reported" ? "*" : ""}</td>
                    <td>{r.succeeded ? <Pill tone="ok">ok</Pill> : <Pill tone="bad">{r.error_code ?? "failed"}</Pill>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[11px] text-[var(--muted)]">* reported by Claude Code</p>
          </div>
        )}
      </Card>
    </div>
  );
}

function StoreBadge({ kind, secure, available }: { kind: string; secure: boolean; available: boolean }) {
  if (!available) return <Pill tone="bad">No secure key store</Pill>;
  const label = kind.includes("Windows") || kind.includes("WinVault") ? "Windows Credential Manager" : kind.includes("macOS") ? "macOS Keychain" : kind;
  return secure ? (
    <span title={kind}><Pill tone="ok"><Lock className="h-3 w-3" aria-hidden /> {label}</Pill></span>
  ) : (
    <span title={kind}><Pill tone="warn"><ShieldAlert className="h-3 w-3" aria-hidden /> Test store — not secure</Pill></span>
  );
}

function AnthropicSection({ run, patch }: { run: (fn: () => Promise<unknown>) => Promise<void>; patch: (p: AISettingsPatch) => Promise<void> }) {
  const { api, ai } = useBackend();
  const [key, setKey] = useState("");
  const [models, setModels] = useState<AIModel[] | null>(null);
  const [testing, setTesting] = useState(false);
  const a = ai!.anthropic;

  useEffect(() => {
    if (!api || !a.configured) return setModels(null);
    api.anthropicModels().then(setModels).catch(() => setModels(null));
  }, [api, a.configured]);

  async function saveKey(e: FormEvent) {
    e.preventDefault();
    if (!key.trim()) return;
    await run(() => api!.setAnthropicKey(key.trim()));
    setKey("");
  }

  const modelOptions: [string, string][] = (models ?? FALLBACK_MODELS.map((id) => ({ id, display_name: id, price_known: true }) as AIModel)).map((mm) => [
    mm.id,
    `${mm.display_name}${mm.price_known ? "" : " (no price data)"}`,
  ]);
  if (!modelOptions.some(([id]) => id === a.settings.model)) modelOptions.unshift([a.settings.model, a.settings.model]);
  const test = a.last_test;

  return (
    <div className="space-y-4 text-sm">
      <p className="text-xs text-[var(--muted)]">
        Pay-as-you-go API access with your own key from console.anthropic.com. This is separate from a Claude Pro or Max subscription; to use a subscription, connect Claude Code instead.
      </p>
      {a.configured ? (
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-2"><KeyRound className="h-4 w-4" aria-hidden /> API key <code data-testid="key-hint">{a.key_hint}</code></span>
          <button type="button" onClick={() => void run(() => api!.deleteAnthropicKey())} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs hover:bg-[var(--hover)]">
            <Trash2 className="h-3.5 w-3.5" aria-hidden /> Remove key
          </button>
        </div>
      ) : (
        <form onSubmit={saveKey} className="flex gap-2">
          <label htmlFor="apikey" className="sr-only">Anthropic API key</label>
          <input id="apikey" type="password" autoComplete="off" spellCheck={false} placeholder="sk-ant-…" value={key} onChange={(e) => setKey(e.target.value)}
            disabled={!ai!.credential_store.available}
            className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono text-xs" />
          <button type="submit" disabled={!key.trim() || !ai!.credential_store.available} className="rounded-lg bg-[var(--accent)] px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">Save key</button>
        </form>
      )}
      {!ai!.credential_store.available && <p className="text-xs text-rose-500">{ai!.credential_store.detail}</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Select id="model" label="Model" value={a.settings.model} onChange={(v) => void patch({ anthropic: { model: v } })} options={modelOptions} />
        <Select id="effort" label="Effort" value={a.settings.effort ?? "medium"} onChange={(v) => void patch({ anthropic: { effort: v as AIEffort } })} options={EFFORTS.map((e) => [e, e])} />
        <NumberField id="timeout" label="Timeout (seconds)" value={a.settings.timeout_s} min={10} max={600} onCommit={(v) => void patch({ anthropic: { timeout_s: v } })} />
        <NumberField id="retries" label="Retries" value={a.settings.max_retries} min={0} max={5} onCommit={(v) => void patch({ anthropic: { max_retries: v } })} />
      </div>
      <Toggle label="If the model declines a request, retry on another Claude model" checked={a.settings.refusal_fallback} onChange={(v) => void patch({ anthropic: { refusal_fallback: v } })}
        hint="Uses the API's built-in fallback (same provider). The model that answered and its price are recorded." />
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" disabled={!a.configured || testing} onClick={() => { setTesting(true); void run(() => api!.testProvider("anthropic")).finally(() => setTesting(false)); }}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium hover:bg-[var(--hover)] disabled:opacity-50">
          <RefreshCw className={`h-3.5 w-3.5 ${testing ? "animate-spin" : ""}`} aria-hidden /> Test connection
        </button>
        {test && <TestOutcome t={test} />}
      </div>
    </div>
  );
}

function ClaudeCodeSection({ run, patch }: { run: (fn: () => Promise<unknown>) => Promise<void>; patch: (p: AISettingsPatch) => Promise<void> }) {
  const { api, ai } = useBackend();
  const c = ai!.claude_code;
  const d = c.detected;
  const [busy, setBusy] = useState(false);
  const act = (fn: () => Promise<unknown>) => { setBusy(true); void run(fn).finally(() => setBusy(false)); };
  return (
    <div className="space-y-4 text-sm">
      <p className="text-xs text-[var(--muted)]">
        Uses the Claude Code app installed on this computer, signed in with its own account (a Claude plan or an API key). JACK runs Claude Code but never reads its sign-in details.
      </p>
      <Toggle label="Use Claude Code" checked={c.settings.enabled} onChange={(v) => void patch({ claude_code: { enabled: v } })} />
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={busy} onClick={() => act(() => api!.detectClaudeCode())} className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium hover:bg-[var(--hover)] disabled:opacity-50">
          <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Detect
        </button>
        <button type="button" disabled={busy || !c.settings.enabled} onClick={() => act(() => api!.testProvider("claude_code"))} className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium hover:bg-[var(--hover)] disabled:opacity-50">
          Test
        </button>
        {c.last_test && <TestOutcome t={c.last_test} />}
      </div>
      {d && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs" aria-label="Claude Code detection">
          <dt className="text-[var(--muted)]">Installed</dt><dd>{d.installed ? `yes — ${d.version ?? "unknown version"}` : "no"}</dd>
          {d.installed && <><dt className="text-[var(--muted)]">Signed in</dt><dd>{d.logged_in ? `yes (${d.auth_method ?? "unknown method"})` : "no"}</dd></>}
          {d.detail && <><dt className="text-[var(--muted)]">Note</dt><dd>{d.detail}</dd></>}
        </dl>
      )}
    </div>
  );
}

function TestConsole() {
  const { api, ai } = useBackend();
  const [prompt, setPrompt] = useState("");
  const [provider, setProvider] = useState<AIProviderId>(ai?.routing.reasoning ?? "anthropic");
  const [res, setRes] = useState<AICompletion | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function send(e: FormEvent) {
    e.preventDefault();
    if (!api || !prompt.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.aiComplete(prompt.trim(), provider));
    } catch (e2) {
      setErr(e2 instanceof ApiRequestError ? e2.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={send} className="space-y-3 text-sm">
      <label htmlFor="console-prompt" className="sr-only">Prompt</label>
      <textarea id="console-prompt" rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Ask Claude something to check the setup…"
        className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2" />
      <div className="flex items-center gap-2">
        <select aria-label="Provider" value={provider} onChange={(e) => setProvider(e.target.value as AIProviderId)} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5 text-xs">
          <option value="anthropic">Anthropic API</option>
          <option value="claude_code">Claude Code</option>
        </select>
        <button type="submit" disabled={busy || !prompt.trim()} className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
          <Send className="h-3.5 w-3.5" aria-hidden /> {busy ? "Waiting…" : "Send"}
        </button>
      </div>
      {err && <p role="alert" className="text-rose-500">{err}</p>}
      {res && (
        <div className="space-y-1 rounded-lg bg-[var(--hover)] p-3" data-testid="console-result">
          {res.stop_reason === "refusal" ? (
            <p className="text-amber-600 dark:text-amber-300">The model declined this request{res.refusal_category ? ` (${res.refusal_category})` : ""}.</p>
          ) : (
            <p className="whitespace-pre-wrap">{res.text}</p>
          )}
          <p className="text-[11px] text-[var(--muted)]">
            {res.model_served}{res.fallbacks.length ? ` (after ${res.fallbacks.map(([f]) => f).join(", ")} declined)` : ""} · {res.usage.reduce((s, u) => s + u.input_tokens, 0)} in / {res.usage.reduce((s, u) => s + u.output_tokens, 0)} out · {res.latency_ms} ms · {res.billing_kind === "api" ? usd(res.cost_usd, 4) : `${usd(res.reported_cost_usd, 4)} reported by Claude Code`}
          </p>
        </div>
      )}
    </form>
  );
}

function LimitsForm({ limits, onSave }: { limits: { monthly_usd: string | null; per_task_usd: string | null; per_project_usd: string | null; alert_pct: number[] }; onSave: (l: AISettingsPatch["limits"]) => void }) {
  const [monthly, setMonthly] = useState(limits.monthly_usd ?? "");
  const [task, setTask] = useState(limits.per_task_usd ?? "");
  const [project, setProject] = useState(limits.per_project_usd ?? "");
  const [alerts, setAlerts] = useState(limits.alert_pct.join(", "));
  useEffect(() => {
    setMonthly(limits.monthly_usd ?? "");
    setTask(limits.per_task_usd ?? "");
    setProject(limits.per_project_usd ?? "");
    setAlerts(limits.alert_pct.join(", "));
  }, [limits]);
  const clean = (v: string) => (v.trim() === "" ? null : v.trim());
  return (
    <form
      className="space-y-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        onSave({
          monthly_usd: clean(monthly),
          per_task_usd: clean(task),
          per_project_usd: clean(project),
          alert_pct: alerts.split(",").map((x) => Number(x.trim())).filter((x) => Number.isFinite(x) && x > 0),
        });
      }}
    >
      <p className="text-xs text-[var(--muted)]">Applies to Anthropic API usage. JACK checks limits before every request and refuses requests once a limit is reached. Leave empty for no limit.</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <Money id="lim-month" label="Monthly ($)" value={monthly} onChange={setMonthly} />
        <Money id="lim-task" label="Per task ($)" value={task} onChange={setTask} />
        <Money id="lim-project" label="Per project ($)" value={project} onChange={setProject} />
      </div>
      <div>
        <label htmlFor="lim-alerts" className="text-xs font-medium">Alert at (% of monthly)</label>
        <input id="lim-alerts" value={alerts} onChange={(e) => setAlerts(e.target.value)} className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2" />
      </div>
      <p className="text-[11px] text-[var(--muted)]">Per-project limits take effect once projects arrive in Milestone 8.</p>
      <button type="submit" className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-white">Save limits</button>
    </form>
  );
}

function TestOutcome({ t }: { t: { ok: boolean; model: string | null; latency_ms: number | null; error: string | null } }) {
  return t.ok ? (
    <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-300" data-testid="test-ok">
      <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> Connected · {t.model} · {t.latency_ms} ms
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-xs text-rose-600 dark:text-rose-300" role="alert">
      <XCircle className="h-3.5 w-3.5" aria-hidden /> {t.error}
    </span>
  );
}

function Select({ id, label, value, onChange, options }: { id: string; label: string; value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium">{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </div>
  );
}

function NumberField({ id, label, value, min, max, onCommit }: { id: string; label: string; value: number; min: number; max: number; onCommit: (v: number) => void }) {
  const [v, setV] = useState(String(value));
  useEffect(() => setV(String(value)), [value]);
  const commit = () => {
    const n = Number(v);
    if (Number.isFinite(n) && n >= min && n <= max && n !== value) onCommit(n);
  };
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium">{label}</label>
      <input id={id} type="number" min={min} max={max} value={v} onChange={(e) => setV(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()}
        className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2" />
    </div>
  );
}

function Money({ id, label, value, onChange }: { id: string; label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium">{label}</label>
      <input id={id} inputMode="decimal" placeholder="no limit" value={value} onChange={(e) => onChange(e.target.value.replace(/[^0-9.]/g, ""))}
        className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2" />
    </div>
  );
}

function Toggle({ label, checked, onChange, hint }: { label: string; checked: boolean; onChange: (v: boolean) => void; hint?: ReactNode }) {
  return (
    <div>
      <label className="flex items-center justify-between gap-4 font-medium">
        {label}
        <input type="checkbox" role="switch" checked={checked} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
      </label>
      {hint && <p className="mt-0.5 text-xs text-[var(--muted)]">{hint}</p>}
    </div>
  );
}
