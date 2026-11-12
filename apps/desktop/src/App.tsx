import { useEffect, useState } from "react";
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

export function App() {
  const [page, setPage] = useState<PageId>("home");
  const [appearance, setAppearance] = useState<Appearance>(loadAppearance);
  const { supervisor, socket } = useBackend();

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", resolveDark(appearance.theme));
    root.style.setProperty("--accent", appearance.accent);
    saveAppearance(appearance);
  }, [appearance]);

  // Keyboard shortcuts: Ctrl/Cmd + 1/2/3/, navigate (shown in NAV); Ctrl+B toggles compact mode.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
      if (e.key.toLowerCase() === "b") {
        e.preventDefault();
        setAppearance((a) => ({ ...a, compact: !a.compact }));
        return;
      }
      const item = NAV.find((n) => n.shortcut === e.key);
      if (item) {
        e.preventDefault();
        setPage(item.id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const item = NAV.find((n) => n.id === page) ?? NAV[0]!;
  let content;
  switch (page) {
    case "home": content = <HomePage />; break;
    case "tasks": content = <TasksPage />; break;
    case "security": content = <SecurityPage />; break;
    case "settings": content = <SettingsPage appearance={appearance} onChange={setAppearance} />; break;
    default: content = <PlannedPage item={item} />;
  }

  return (
    <div className="flex h-screen bg-[var(--bg)] text-[var(--text)]">
      <Sidebar current={page} onNavigate={setPage} compact={appearance.compact} />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-[var(--border)] px-8 py-4">
          <h1 className="text-xl font-semibold">{item.label}</h1>
          <div className="flex items-center gap-2" aria-label="Connection status">
            <Pill tone={healthTone(supervisor.state)}>service {supervisor.state}</Pill>
            <Pill tone={healthTone(socket)}>live {socket}</Pill>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto p-8">{content}</div>
      </main>
    </div>
  );
}
