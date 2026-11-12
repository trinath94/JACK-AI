import { Keyboard } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { NotificationCentre } from "./components/NotificationCentre";
import { ShortcutsDialog, type ShortcutRow } from "./components/ShortcutsDialog";
import { Sidebar } from "./components/Sidebar";
import { Pill, healthTone } from "./components/ui";
import { loadAppearance, resolveDark, saveAppearance, type Appearance } from "./lib/appearance";
import { useBackend } from "./lib/backend";
import { NAV, type PageId } from "./lib/nav";
import { HomePage } from "./pages/HomePage";
import { PlannedPage } from "./pages/PlannedPage";
import { SecurityPage } from "./pages/SecurityPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TasksPage } from "./pages/TasksPage";
import { UsagePage } from "./pages/UsagePage";
import { VoicePage } from "./pages/VoicePage";

export function shortcutRows(ptt: string | null): ShortcutRow[] {
  return [
    ...(ptt ? [{ keys: ptt, action: "Hold to talk (works anywhere in Windows)" }] : []),
    { keys: "Ctrl+K", action: "Type a command" },
    ...NAV.filter((n) => n.shortcut)
      // Number keys first (Ctrl+1…), then the rest (Ctrl+,).
      .sort((a, b) => Number(!/\d/.test(a.shortcut!)) - Number(!/\d/.test(b.shortcut!)) || a.shortcut!.localeCompare(b.shortcut!))
      .map((n) => ({ keys: `Ctrl+${n.shortcut}`, action: `Open ${n.label}` })),
    { keys: "Ctrl+B", action: "Toggle compact sidebar" },
    { keys: "?", action: "Show keyboard shortcuts" },
    { keys: "Esc", action: "Close dialogs and panels" },
  ];
}

const VOICE_TONE = { listening: "bad", processing: "accent", speaking: "accent", disabled: "warn", idle: "muted", standby: "ok" } as const;
const VOICE_LABEL = { listening: "listening", processing: "thinking", speaking: "speaking", idle: "voice ready", standby: "wake word on" } as const;

export function App() {
  const [page, setPage] = useState<PageId>("home");
  const [appearance, setAppearance] = useState<Appearance>(loadAppearance);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [ptt, setPtt] = useState<string | null>(null);
  const commandRef = useRef<HTMLInputElement>(null);
  const { supervisor, socket, voice, bridge } = useBackend();

  useEffect(() => {
    void bridge.pttShortcut().then(setPtt).catch(() => setPtt(null));
  }, [bridge]);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", resolveDark(appearance.theme));
    root.style.setProperty("--accent", appearance.accent);
    saveAppearance(appearance);
    if (appearance.theme !== "system") return;
    // Follow the OS theme live while "system" is selected.
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const onChange = () => root.classList.toggle("dark", mq.matches);
    mq?.addEventListener?.("change", onChange);
    return () => mq?.removeEventListener?.("change", onChange);
  }, [appearance]);

  const focusCommand = useCallback(() => {
    setPage("home");
    // Wait a frame for the Home page to mount.
    requestAnimationFrame(() => commandRef.current?.focus());
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
      if (e.key === "?" && !typing && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        setShowShortcuts(true);
        return;
      }
      if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return;
      const key = e.key.toLowerCase();
      if (key === "b") {
        e.preventDefault();
        setAppearance((a) => ({ ...a, compact: !a.compact }));
      } else if (key === "k") {
        e.preventDefault();
        focusCommand();
      } else {
        const item = NAV.find((n) => n.shortcut === e.key);
        if (item) {
          e.preventDefault();
          setPage(item.id);
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusCommand]);

  const item = NAV.find((n) => n.id === page) ?? NAV[0]!;
  let content;
  switch (page) {
    case "home": content = <HomePage commandRef={commandRef} shortcut={ptt} />; break;
    case "voice": content = <VoicePage shortcut={ptt} />; break;
    case "tasks": content = <TasksPage />; break;
    case "usage": content = <UsagePage />; break;
    case "security": content = <SecurityPage />; break;
    case "settings": content = <SettingsPage appearance={appearance} onChange={setAppearance} shortcuts={shortcutRows(ptt)} />; break;
    default: content = <PlannedPage item={item} />;
  }

  return (
    <div className="flex h-screen bg-[var(--bg)] text-[var(--text)]">
      <Sidebar current={page} onNavigate={setPage} compact={appearance.compact} />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-4 border-b border-[var(--border)] px-4 py-3 md:px-8">
          <h1 className="truncate text-xl font-semibold">{item.label}</h1>
          <div className="flex items-center gap-2" aria-label="Status">
            {voice && (
              <span data-testid="voice-status">
                <Pill tone={VOICE_TONE[voice.state]}>
                  {voice.state === "disabled" ? (voice.settings.privacy_mode ? "privacy mode" : "mic muted") : VOICE_LABEL[voice.state]}
                </Pill>
              </span>
            )}
            <span className="hidden sm:inline"><Pill tone={healthTone(supervisor.state)}>service {supervisor.state}</Pill></span>
            <span className="hidden sm:inline"><Pill tone={healthTone(socket)}>live {socket}</Pill></span>
            <button type="button" onClick={() => setShowShortcuts(true)} aria-label="Keyboard shortcuts" className="rounded-lg p-2 hover:bg-[var(--hover)]">
              <Keyboard className="h-5 w-5" aria-hidden />
            </button>
            <NotificationCentre />
          </div>
        </header>
        <div className="flex-1 overflow-y-auto p-4 md:p-8">{content}</div>
      </main>
      {showShortcuts && <ShortcutsDialog rows={shortcutRows(ptt)} onClose={() => setShowShortcuts(false)} />}
    </div>
  );
}
