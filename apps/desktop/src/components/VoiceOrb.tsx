import { motion, useReducedMotion } from "framer-motion";

export type OrbState = "offline" | "disabled" | "idle" | "listening" | "processing" | "speaking";

const LABEL: Record<OrbState, string> = {
  offline: "Service offline",
  disabled: "Microphone off",
  idle: "Ready",
  listening: "Listening",
  processing: "Processing",
  speaking: "Speaking",
};

/**
 * Central JACK orb. `level` (0..1) is the live microphone input level while listening, so
 * the orb visibly responds to the user's voice.
 */
export function VoiceOrb({ state, level = 0, size = 160 }: { state: OrbState; level?: number; size?: number }) {
  const reduce = useReducedMotion();
  const listening = state === "listening";
  const dim = state === "offline" || state === "disabled";
  const scale = listening ? 1 + Math.min(level, 1) * 0.18 : 1;
  const breathe =
    reduce || listening
      ? {}
      : {
          scale: state === "speaking" ? [1, 1.07, 1] : state === "processing" ? [1, 1.03, 1] : [1, 1.015, 1],
        };
  return (
    <div className="flex flex-col items-center gap-4" role="status" aria-live="polite" aria-label={`JACK: ${LABEL[state]}`}>
      <div className="relative grid place-items-center" style={{ width: size * 1.3, height: size * 1.3 }}>
        {!reduce && !dim && (
          <motion.div
            aria-hidden
            className="absolute inset-0 rounded-full"
            style={{ background: "radial-gradient(circle, var(--accent) 0%, transparent 70%)" }}
            animate={
              listening
                ? { opacity: 0.25 + level * 0.5, scale: 0.95 + level * 0.3 }
                : { opacity: [0.18, 0.35, 0.18], scale: [0.95, 1.12, 0.95] }
            }
            transition={listening ? { duration: 0.08 } : { duration: state === "speaking" ? 1.4 : 4, repeat: Infinity, ease: "easeInOut" }}
          />
        )}
        {state === "processing" && !reduce && (
          <motion.div
            aria-hidden
            className="absolute rounded-full border-2 border-transparent border-t-[var(--accent)]"
            style={{ width: size * 1.15, height: size * 1.15 }}
            animate={{ rotate: 360 }}
            transition={{ duration: 1.2, repeat: Infinity, ease: "linear" }}
          />
        )}
        <motion.div
          className="relative rounded-full ring-1 ring-white/20"
          style={{
            width: size,
            height: size,
            background: "radial-gradient(circle at 40% 35%, #e0f2fe 0%, var(--accent) 45%, #1e1b4b 100%)",
            boxShadow: `0 0 ${60 + level * 80}px -10px var(--accent)`,
            filter: dim ? "grayscale(1)" : undefined,
            opacity: dim ? 0.5 : 1,
          }}
          animate={listening ? { scale } : breathe}
          transition={listening ? { duration: 0.08 } : { duration: 3.5, repeat: Infinity, ease: "easeInOut" }}
          data-state={state}
          data-testid="voice-orb"
        />
      </div>
      <p className="text-sm font-medium text-[var(--muted)]">{LABEL[state]}</p>
    </div>
  );
}
