import { Construction } from "lucide-react";
import { Card } from "../components/ui";
import type { NavItem } from "../lib/nav";

/** Honest placeholder: the section exists in navigation but its milestone has not shipped. */
export function PlannedPage({ item }: { item: NavItem }) {
  return (
    <Card>
      <div className="flex flex-col items-center gap-3 py-16 text-center">
        <Construction className="h-10 w-10 text-[var(--muted)]" aria-hidden />
        <h2 className="text-lg font-semibold">{item.label} is not implemented yet</h2>
        <p className="max-w-md text-sm text-[var(--muted)]">{item.summary}</p>
        <p className="text-sm">
          Scheduled for <strong>Milestone {item.milestone}</strong> — see <code>docs/ROADMAP.md</code>.
        </p>
      </div>
    </Card>
  );
}
