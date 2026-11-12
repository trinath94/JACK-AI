import { motion, useReducedMotion } from "framer-motion";

export type OrbState = "offline" | "idle" | "listening" | "processing" | "speaking";

const LABEL: Record<OrbState, string> = {
  offline: "Service offline",
  idle: "Ready",
  listening: "Listening",
  processing: "Processing",
  speaking: "Speaking",
};

/**
 * Central JACK orb. In Milestone 1 it reflects service readiness only; the listening /
 * processing / speaking states are driven by the voice engine from Milestone 3.
 */
export function VoiceOrb({ state }: { state: OrbState }) {
  const reduce = useReducedMotion();
  const active = state === "listening" || state === "speaking";
  const pulse = reduce
    ? {}
    : {
        scale: active ? [1, 1.08, 1] : state === "processing" ? [1, 1.03, 1] : [1, 1.015, 1],
        opacity: state === "offline" ? 0.45 : 1,
      };
  return (
    <div className="flex flex-col items-center gap-4" role="status" aria-live="polite">
      <div className="relative grid h-52 w-52 place-items-center">
        {!reduce && state !== "offline" && (
          <motion.div
            aria-hidden
            className="absolute inset-0 rounded-full"
            style={{ background: "radial-gradient(circle, var(--accent) 0%, transparent 70%)" }}
            animate={{ opacity: [0.18, 0.35, 0.18], scale: [0.95, 1.12, 0.95] }}
            transition={{ duration: active ? 1.4 : 4, repeat: Infinity, ease: "easeInOut" }}
          />
        )}
        <motion.div
          className="relative h-40 w-40 rounded-full ring-1 ring-white/20"
          style={{
            background:
              "radial-gradient(circle at 40% 35%, #e0f2fe 0%, var(--accent) 45%, #1e1b4b 100%)",
            boxShadow: "0 0 60px -10px var(--accent)",
            filter: state === "offline" ? "grayscale(1)" : undefined,
          }}
          animate={pulse}
          transition={{ duration: active ? 1.2 : 3.5, repeat: Infinity, ease: "easeInOut" }}
          data-state={state}
          data-testid="voice-orb"
        />
      </div>
      <p className="text-sm font-medium text-[var(--muted)]">{LABEL[state]}</p>
    </div>
  );
}
