import type {
  DiscoveryAnswer,
  DiscoveryEngineStatus,
  DiscoveryResult,
  DiscoverySession,
  DiscoveryStatus,
  ProjectSpec,
  SlotValue,
  SpecItem,
} from "@jack/shared-types";
import { Check, CheckCircle2, CornerDownLeft, Mic, Pencil, Plus, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Card, Pill, formatTime } from "../components/ui";
import { ApiRequestError } from "../lib/api";
import { useBackend } from "../lib/backend";

const STATUS: Record<DiscoveryStatus, [string, "ok" | "warn" | "bad" | "muted" | "accent"]> = {
  choosing_category: ["clarifying", "accent"],
  asking: ["asking", "accent"],
  resolving_conflict: ["conflict", "warn"],
  awaiting_approval: ["needs approval", "warn"],
  changing: ["changing", "accent"],
  ready: ["ready for planning", "ok"],
  cancelled: ["cancelled", "muted"],
  blocked: ["stopped", "bad"],
};

const SOURCE: Record<string, [string, "ok" | "muted" | "accent"]> = {
  user: ["you said", "ok"],
  inferred: ["understood", "accent"],
  default: ["assumed", "muted"],
};

const OPEN = new Set<DiscoveryStatus>(["choosing_category", "asking", "resolving_conflict", "awaiting_approval", "changing"]);

export function CommandPage() {
  const { api, discoveryTick, voice, followUpUntil } = useBackend();
  const [sessions, setSessions] = useState<DiscoverySession[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [session, setSession] = useState<DiscoverySession | null>(null);
  const [engine, setEngine] = useState<DiscoveryEngineStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!api) return;
    const [list, eng] = await Promise.all([api.discoverySessions(false), api.discoveryStatus()]);
    setSessions(list);
    setEngine(eng);
    const id = selected ?? list.find((s) => OPEN.has(s.status))?.id ?? list[0]?.id ?? null;
    if (id && id !== selected) setSelected(id);
    setSession(id ? await api.discoverySession(id) : null);
  }, [api, selected]);

  useEffect(() => {
    void load().catch(() => {});
  }, [load, discoveryTick]);

  async function act(fn: () => Promise<DiscoveryResult>) {
    setBusy(true);
    setError(null);
    try {
      const r = await fn();
      setSelected(r.session.id);
      setSession(r.session);
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const listening = voice?.state === "listening" && followUpUntil !== null && followUpUntil > Date.now();

  return (
    <div className="grid gap-4 xl:grid-cols-[16rem_1fr]">
      <div className="space-y-4">
        <Card title="Conversations" action={
          <button type="button" onClick={() => { setSelected(null); setSession(null); }} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--hover)]">
            <Plus className="h-3.5 w-3.5" aria-hidden /> New request
          </button>
        }>
          {sessions.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">No requests yet. Type one, or say “Jack, build a professional website”.</p>
          ) : (
            <ul className="space-y-1" aria-label="Conversations">
              {sessions.map((s) => (
                <li key={s.id}>
                  <button type="button" onClick={() => setSelected(s.id)} aria-current={s.id === selected}
                    className={`w-full rounded-lg px-2 py-1.5 text-left text-sm hover:bg-[var(--hover)] ${s.id === selected ? "bg-[var(--hover)]" : ""}`}>
                    <span className="block truncate">{s.spec?.title ?? s.command}</span>
                    <span className="mt-0.5 flex items-center gap-2 text-xs text-[var(--muted)]">
                      <Pill tone={STATUS[s.status][1]}>{STATUS[s.status][0]}</Pill>
                      {s.category_name ?? "—"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        {engine && api && <EngineCard engine={engine} onChange={(p) => void api.updateDiscoverySettings(p).then(() => load())} />}
      </div>

      <div className="space-y-4">
        <Card title={session ? (session.category_name ?? "New request") : "New request"}
          action={session && <Pill tone={STATUS[session.status][1]}>{STATUS[session.status][0]}</Pill>}>
          {session ? (
            <Conversation session={session} busy={busy} listening={listening}
              onSend={(text) => act(() => api!.discoveryMessage(text, session.id))}
              onCancel={() => act(() => api!.cancelDiscovery(session.id))} />
          ) : (
            <NewRequest busy={busy} onSend={(text) => act(() => api!.discoveryMessage(text))} />
          )}
          {error && <p role="alert" className="mt-3 text-sm text-rose-500">{error}</p>}
        </Card>
        {session?.spec && (
          <SpecCard session={session} spec={session.spec} busy={busy}
            onApprove={() => act(() => api!.approveSpec(session.id))}
            onEdit={(slot, value) => act(() => api!.setDiscoveryAnswer(session.id, slot, value))} />
        )}
        {session && !session.spec && session.answers.length > 0 && (
          <Card title="What JACK knows so far">
            <AnswerList answers={session.answers} editable={OPEN.has(session.status)}
              onEdit={(slot, value) => act(() => api!.setDiscoveryAnswer(session.id, slot, value))} />
          </Card>
        )}
      </div>
    </div>
  );
}

function NewRequest({ busy, onSend }: { busy: boolean; onSend: (t: string) => void }) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-[var(--muted)]">
        Describe what you'd like built or done. JACK works out what kind of job it is, asks only the questions it needs (one at a time), and writes a specification.
      </p>
      <MessageForm busy={busy} placeholder="e.g. Build a professional website for my company" label="New request" onSend={onSend} autoFocus />
    </div>
  );
}

function Conversation({ session, busy, listening, onSend, onCancel }: {
  session: DiscoverySession; busy: boolean; listening: boolean; onSend: (t: string) => void; onCancel: () => void;
}) {
  const end = useRef<HTMLDivElement>(null);
  const turns = session.turns ?? [];
  useEffect(() => end.current?.scrollIntoView?.({ block: "nearest" }), [turns.length]);
  const open = OPEN.has(session.status);
  const q = session.question;
  const options: string[] =
    q?.kind === "slot" && q.input === "bool" ? ["Yes", "No"] : (q?.options ?? []).map((o) => o.label);
  return (
    <div className="space-y-3">
      <ol className="max-h-[22rem] space-y-2 overflow-y-auto pr-1" aria-label="Conversation">
        {turns.map((t, i) => (
          <li key={i} className={`flex ${t.role === "user" ? "justify-end" : ""}`}>
            <span className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm ${t.role === "user" ? "bg-[var(--accent)] text-white" : "bg-[var(--hover)]"}`}>
              {t.role === "user" && t.source === "voice" && <Mic className="mr-1 inline h-3 w-3" aria-label="spoken" />}
              {t.text}
            </span>
          </li>
        ))}
        <div ref={end} />
      </ol>
      {listening && (
        <p className="flex items-center gap-2 text-xs text-rose-500" role="status">
          <span className="h-2 w-2 animate-pulse rounded-full bg-rose-500" /> Listening for your answer — just speak.
        </p>
      )}
      {open && options.length > 0 && (
        <div className="flex flex-wrap gap-2" aria-label="Suggested answers">
          {options.map((o) => (
            <button key={o} type="button" disabled={busy} onClick={() => onSend(o)}
              className="rounded-full border border-[var(--border)] px-3 py-1 text-xs hover:bg-[var(--hover)] disabled:opacity-50">{o}</button>
          ))}
          {q?.kind === "slot" && (
            <button type="button" disabled={busy} onClick={() => onSend("you decide")}
              className="rounded-full border border-dashed border-[var(--border)] px-3 py-1 text-xs text-[var(--muted)] hover:bg-[var(--hover)]">You decide</button>
          )}
        </div>
      )}
      {open ? (
        <div className="flex items-start gap-2">
          <div className="flex-1"><MessageForm busy={busy} placeholder="Answer JACK…" label="Your answer" onSend={onSend} autoFocus /></div>
          <button type="button" onClick={onCancel} disabled={busy} className="inline-flex items-center gap-1 rounded-xl border border-[var(--border)] px-3 py-3 text-xs hover:bg-[var(--hover)]">
            <X className="h-3.5 w-3.5" aria-hidden /> Cancel request
          </button>
        </div>
      ) : session.status === "ready" ? (
        <p className="flex items-center gap-2 text-sm text-emerald-600 dark:text-emerald-300">
          <CheckCircle2 className="h-4 w-4" aria-hidden /> Specification complete. The task waits in planning — planning and building arrive in later milestones.
        </p>
      ) : session.blocked_reason ? (
        <p className="text-sm text-rose-500">{session.blocked_reason}</p>
      ) : null}
    </div>
  );
}

function MessageForm({ busy, placeholder, label, onSend, autoFocus }: {
  busy: boolean; placeholder: string; label: string; onSend: (t: string) => void; autoFocus?: boolean;
}) {
  const [text, setText] = useState("");
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    onSend(text.trim());
    setText("");
  }
  return (
    <form onSubmit={submit} className="flex gap-2">
      <label className="sr-only" htmlFor={`msg-${label}`}>{label}</label>
      <input id={`msg-${label}`} value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder} maxLength={4000}
        autoFocus={autoFocus} disabled={busy}
        className="min-w-0 flex-1 rounded-xl border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-[var(--accent)] disabled:opacity-60" />
      <button type="submit" disabled={busy || !text.trim()} className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-3 text-sm font-semibold text-white disabled:opacity-50">
        <CornerDownLeft className="h-4 w-4" aria-hidden /> Send
      </button>
    </form>
  );
}

function SpecCard({ session, spec, busy, onApprove, onEdit }: {
  session: DiscoverySession; spec: ProjectSpec; busy: boolean; onApprove: () => void; onEdit: (slot: string, v: SlotValue) => void;
}) {
  const editable = session.status !== "cancelled" && session.status !== "blocked";
  const byslot = new Map(session.answers.map((a) => [a.slot, a]));
  const scaleTone = spec.scope.scale === "large" ? "warn" : spec.scope.scale === "medium" ? "accent" : "ok";
  return (
    <Card title="Specification" action={<Pill tone={scaleTone}>{spec.scope.scale} job</Pill>}>
      <div className="space-y-4 text-sm">
        <div>
          <h3 className="text-lg font-semibold" data-testid="spec-title">{spec.title}</h3>
          <p className="text-[var(--muted)]">{spec.summary}</p>
        </div>
        <section>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">Requirements</h4>
          <SpecItems items={spec.requirements} byslot={byslot} editable={editable} onEdit={onEdit} />
        </section>
        {spec.assumptions.length > 0 && (
          <section>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">Assumptions (change any you disagree with)</h4>
            <SpecItems items={spec.assumptions} byslot={byslot} editable={editable} onEdit={onEdit} />
          </section>
        )}
        <div className="grid gap-4 md:grid-cols-2">
          <section>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">Scope — {spec.scope.rationale}</h4>
            <ul className="list-inside list-disc">{spec.scope.components.map((c) => <li key={c}>{c}</li>)}</ul>
          </section>
          <section>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">External integrations</h4>
            {spec.integrations.length ? (
              <ul className="space-y-1">{spec.integrations.map((i) => <li key={i.name}>{i.name} <span className="text-xs text-[var(--muted)]">— {i.reason}</span></li>)}</ul>
            ) : <p className="text-[var(--muted)]">None</p>}
            <h4 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">Hosting</h4>
            <p>{spec.hosting.display}</p>
          </section>
        </div>
        <section>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">What JACK still needs to build this</h4>
          <ul className="space-y-1">
            {spec.dependencies.map((d) => (
              <li key={d.capability} className="flex items-center justify-between gap-2">
                <span>{d.capability}</span>
                <Pill tone={d.available ? "ok" : "muted"}>{d.available ? "available" : `Milestone ${d.milestone}`}</Pill>
              </li>
            ))}
          </ul>
        </section>
        {spec.open_questions.length > 0 && (
          <section>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-amber-600">Still to decide</h4>
            <ul className="list-inside list-disc">{spec.open_questions.map((q) => <li key={q}>{q}</li>)}</ul>
          </section>
        )}
        {spec.notes.length > 0 && (
          <section>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">Notes</h4>
            <ul className="list-inside list-disc text-[var(--muted)]">{spec.notes.map((n) => <li key={n}>{n}</li>)}</ul>
          </section>
        )}
        <p className="text-xs text-[var(--muted)]">
          Understood by {spec.engines.some((e) => e.startsWith("claude")) ? "Claude" : "JACK's local rules"} · {session.approved_at ? `approved ${formatTime(session.approved_at)}` : spec.approval_required ? "needs your approval" : "small job — no approval needed"}
        </p>
        {session.status === "awaiting_approval" && (
          <button type="button" onClick={onApprove} disabled={busy}
            className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
            <Check className="h-4 w-4" aria-hidden /> Approve specification
          </button>
        )}
      </div>
    </Card>
  );
}

function SpecItems({ items, byslot, editable, onEdit }: {
  items: SpecItem[]; byslot: Map<string, DiscoveryAnswer>; editable: boolean; onEdit: (slot: string, v: SlotValue) => void;
}) {
  return (
    <AnswerList answers={items.map((i) => byslot.get(i.slot) ?? ({ ...i, input: "text", options: [] } as DiscoveryAnswer))}
      editable={editable} onEdit={onEdit} />
  );
}

function AnswerList({ answers, editable, onEdit }: {
  answers: DiscoveryAnswer[]; editable: boolean; onEdit: (slot: string, v: SlotValue) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  return (
    <dl className="divide-y divide-[var(--border)]">
      {answers.map((a) => (
        <div key={a.slot} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
          <dt className="text-[var(--muted)]">{a.label}</dt>
          <dd className="flex items-center gap-2">
            {editing === a.slot ? (
              <AnswerEditor answer={a} onCancel={() => setEditing(null)} onSave={(v) => { setEditing(null); onEdit(a.slot, v); }} />
            ) : (
              <>
                <span data-testid={`answer-${a.slot}`}>{a.display}</span>
                <Pill tone={SOURCE[a.source]?.[1] ?? "muted"}>{SOURCE[a.source]?.[0] ?? a.source}</Pill>
                {editable && (
                  <button type="button" onClick={() => setEditing(a.slot)} aria-label={`Change ${a.label}`} className="rounded p-1 hover:bg-[var(--hover)]">
                    <Pencil className="h-3.5 w-3.5" aria-hidden />
                  </button>
                )}
              </>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function AnswerEditor({ answer, onSave, onCancel }: { answer: DiscoveryAnswer; onSave: (v: SlotValue) => void; onCancel: () => void }) {
  const [value, setValue] = useState<SlotValue>(answer.value);
  const field = "rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-sm";
  let input;
  if (answer.input === "choice") {
    input = (
      <select aria-label={answer.label} className={field} value={String(value ?? "")} onChange={(e) => setValue(e.target.value)}>
        {answer.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  } else if (answer.input === "multi") {
    const cur = new Set(Array.isArray(value) ? value : []);
    input = (
      <span className="flex flex-wrap gap-2" role="group" aria-label={answer.label}>
        {answer.options.map((o) => (
          <label key={o.value} className="inline-flex items-center gap-1 text-xs">
            <input type="checkbox" checked={cur.has(o.value)} onChange={(e) => {
              const next = new Set(cur);
              if (e.target.checked) next.add(o.value); else next.delete(o.value);
              setValue(answer.options.map((x) => x.value).filter((x) => next.has(x)));
            }} /> {o.label}
          </label>
        ))}
      </span>
    );
  } else if (answer.input === "bool") {
    input = (
      <select aria-label={answer.label} className={field} value={value ? "yes" : "no"} onChange={(e) => setValue(e.target.value === "yes")}>
        <option value="yes">Yes</option><option value="no">No</option>
      </select>
    );
  } else {
    input = <input aria-label={answer.label} className={field} value={String(value ?? "")} maxLength={500} onChange={(e) => setValue(e.target.value)} />;
  }
  return (
    <span className="flex flex-wrap items-center gap-2">
      {input}
      <button type="button" onClick={() => onSave(value)} className="rounded-lg bg-[var(--accent)] px-2 py-1 text-xs font-semibold text-white">Save</button>
      <button type="button" onClick={onCancel} className="rounded-lg border border-[var(--border)] px-2 py-1 text-xs">Cancel</button>
    </span>
  );
}

function EngineCard({ engine, onChange }: { engine: DiscoveryEngineStatus; onChange: (p: Partial<DiscoveryEngineStatus["settings"]>) => void }) {
  const s = engine.settings;
  const sel = "w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5 text-sm";
  return (
    <Card title="How JACK asks">
      <div className="space-y-3 text-sm">
        <p className="flex items-center gap-2">
          Understanding: <Pill tone={engine.using === "claude" ? "ok" : "muted"}>{engine.using === "claude" ? "Claude" : "local rules"}</Pill>
        </p>
        {engine.detail && <p className="text-xs text-[var(--muted)]">{engine.detail}</p>}
        <label className="block">
          <span className="text-xs text-[var(--muted)]">Understanding engine</span>
          <select className={sel} value={s.engine} onChange={(e) => onChange({ engine: e.target.value as "auto" | "local" })}>
            <option value="auto">Claude when set up (recommended)</option>
            <option value="local">Local rules only (nothing sent to Claude)</option>
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-[var(--muted)]">Ask for approval</span>
          <select className={sel} value={s.approval} onChange={(e) => onChange({ approval: e.target.value as "auto" | "always" })}>
            <option value="auto">For medium and large jobs</option>
            <option value="always">For every job</option>
          </select>
        </label>
        <label className="flex items-center justify-between gap-2">
          <span>Listen for my answer after a spoken question</span>
          <input type="checkbox" role="switch" checked={s.followup_listen} onChange={(e) => onChange({ followup_listen: e.target.checked })} className="h-4 w-4 accent-[var(--accent)]" />
        </label>
      </div>
    </Card>
  );
}
