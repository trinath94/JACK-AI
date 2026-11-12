export interface Appearance {
  theme: "system" | "dark" | "light";
  accent: string;
  compact: boolean;
}

export const ACCENTS = [
  { name: "Sky", value: "#0ea5e9" },
  { name: "Violet", value: "#8b5cf6" },
  { name: "Emerald", value: "#10b981" },
  { name: "Amber", value: "#f59e0b" },
  { name: "Rose", value: "#f43f5e" },
] as const;

const KEY = "jack.appearance";
export const DEFAULT_APPEARANCE: Appearance = { theme: "dark", accent: ACCENTS[0].value, compact: false };

export function loadAppearance(): Appearance {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return { ...DEFAULT_APPEARANCE, ...(JSON.parse(raw) as Partial<Appearance>) };
  } catch {
    /* storage unavailable */
  }
  return DEFAULT_APPEARANCE;
}

export function saveAppearance(a: Appearance) {
  try {
    localStorage.setItem(KEY, JSON.stringify(a));
  } catch {
    /* storage unavailable */
  }
}

export function resolveDark(theme: Appearance["theme"]): boolean {
  if (theme === "system") return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? true;
  return theme === "dark";
}
