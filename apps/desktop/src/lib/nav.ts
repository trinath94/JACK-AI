import {
  Activity,
  Bot,
  BookOpen,
  Code2,
  CreditCard,
  FlaskConical,
  FolderKanban,
  GitBranch,
  Home,
  Mic,
  Palette,
  Rocket,
  Server,
  Settings,
  Shield,
  TerminalSquare,
  type LucideIcon,
} from "lucide-react";

export type PageId =
  | "home" | "voice" | "command" | "tasks" | "projects" | "github" | "servers" | "dev"
  | "creative" | "agents" | "testing" | "deployments" | "knowledge" | "security" | "usage"
  | "settings";

export interface NavItem {
  id: PageId;
  label: string;
  icon: LucideIcon;
  /** Milestone that delivers this section; `null` when usable today. */
  milestone: number | null;
  summary: string;
  shortcut?: string;
}

// Section 21 navigation, in order. `milestone` drives honest "planned" states in the UI.
export const NAV: NavItem[] = [
  { id: "home", label: "Home", icon: Home, milestone: null, summary: "Service health, command entry and live task feed.", shortcut: "1" },
  { id: "voice", label: "Voice Assistant", icon: Mic, milestone: 3, summary: "Wake word \"Jack\", push-to-talk, speech recognition and spoken replies." },
  { id: "command", label: "Command Centre", icon: TerminalSquare, milestone: 5, summary: "Requirement discovery: JACK asks one question at a time and builds a specification." },
  { id: "tasks", label: "Active Tasks", icon: Activity, milestone: null, summary: "Durable tasks with lifecycle history; pause, resume and cancel.", shortcut: "2" },
  { id: "projects", label: "Projects", icon: FolderKanban, milestone: 8, summary: "Project records, workspaces and history." },
  { id: "github", label: "GitHub", icon: GitBranch, milestone: 9, summary: "OAuth / fine-grained PAT accounts, repositories, branches and pull requests." },
  { id: "servers", label: "Servers", icon: Server, milestone: 10, summary: "SSH profiles with host-key verification and diagnostics." },
  { id: "dev", label: "Development Studio", icon: Code2, milestone: 11, summary: "Autonomous development in isolated workspaces." },
  { id: "creative", label: "Creative Studio", icon: Palette, milestone: 14, summary: "Image generation and editing through configured providers." },
  { id: "agents", label: "AI Agents", icon: Bot, milestone: 7, summary: "17 specialised agents with least-privilege tool access." },
  { id: "testing", label: "Testing", icon: FlaskConical, milestone: 12, summary: "Test runs, evidence and bounded self-healing." },
  { id: "deployments", label: "Deployments", icon: Rocket, milestone: 13, summary: "Staging and approval-gated production deployments with rollback." },
  { id: "knowledge", label: "Knowledge Base", icon: BookOpen, milestone: 8, summary: "Project memory and semantic search." },
  { id: "security", label: "Security", icon: Shield, milestone: null, summary: "Tamper-evident audit log and chain verification.", shortcut: "3" },
  { id: "usage", label: "Usage and Billing", icon: CreditCard, milestone: 4, summary: "API tokens, cost, and spending limits — API billing shown separately from subscriptions." },
  { id: "settings", label: "Settings", icon: Settings, milestone: null, summary: "Appearance and service information.", shortcut: "," },
];
