import { NAV, type PageId } from "../lib/nav";

export function Sidebar({
  current,
  onNavigate,
  compact,
}: {
  current: PageId;
  onNavigate: (id: PageId) => void;
  compact: boolean;
}) {
  return (
    <nav
      aria-label="Main navigation"
      className={`flex shrink-0 flex-col border-r border-[var(--border)] bg-[var(--sidebar)] ${compact ? "w-16" : "w-60"}`}
    >
      <div className="flex items-center gap-3 px-4 py-5">
        <img src="/jack.svg" alt="" className="h-8 w-8" />
        {!compact && (
          <div>
            <div className="text-base font-bold tracking-[0.2em]">JACK AI</div>
            <div className="text-[10px] tracking-wider text-[var(--muted)]">GIVE THE COMMAND. JACK DELIVERS.</div>
          </div>
        )}
      </div>
      <ul className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-4">
        {NAV.map((item) => {
          const Icon = item.icon;
          const active = item.id === current;
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onNavigate(item.id)}
                aria-current={active ? "page" : undefined}
                title={compact ? item.label : undefined}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                  active
                    ? "bg-[var(--accent)]/15 font-semibold text-[var(--accent)]"
                    : "text-[var(--text)]/80 hover:bg-[var(--hover)]"
                }`}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden />
                {!compact && <span className="flex-1 truncate">{item.label}</span>}
                {!compact && item.milestone !== null && (
                  <span className="text-[10px] text-[var(--muted)]">M{item.milestone}</span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
