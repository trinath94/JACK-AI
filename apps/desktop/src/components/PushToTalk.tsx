import { Mic, MicOff } from "lucide-react";
import { useEffect, useRef } from "react";
import { useBackend } from "../lib/backend";

/**
 * Hold-to-talk button (pointer or Space/Enter while focused). Mirrors the global hotkey.
 * The microphone opens only while held; the service closes it on release or after the
 * configured maximum duration.
 */
export function PushToTalk({ shortcut }: { shortcut: string | null }) {
  const { voice, startPtt, stopPtt, socket } = useBackend();
  const held = useRef(false);
  const listening = voice?.state === "listening";
  const reason = !voice
    ? "Service not connected"
    : voice.settings.privacy_mode
      ? "Privacy mode is on"
      : voice.settings.muted
        ? "Microphone is muted"
        : !voice.capabilities.capture
          ? voice.capabilities.capture_detail ?? "Microphone unavailable"
          : null;
  const disabled = reason !== null || socket !== "open";

  const press = () => {
    if (disabled || held.current) return;
    held.current = true;
    void startPtt();
  };
  const release = () => {
    if (!held.current) return;
    held.current = false;
    void stopPtt();
  };

  // If the window loses focus mid-press, make sure the microphone closes.
  useEffect(() => {
    const onBlur = () => release();
    window.addEventListener("blur", onBlur);
    return () => window.removeEventListener("blur", onBlur);
  });

  return (
    <div className="flex flex-col items-center gap-1.5">
      <button
        type="button"
        disabled={disabled}
        aria-pressed={listening}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture?.(e.pointerId);
          press();
        }}
        onPointerUp={release}
        onPointerCancel={release}
        onKeyDown={(e) => {
          if ((e.key === " " || e.key === "Enter") && !e.repeat) {
            e.preventDefault();
            press();
          }
        }}
        onKeyUp={(e) => {
          if (e.key === " " || e.key === "Enter") release();
        }}
        className={`inline-flex select-none items-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
          listening ? "bg-rose-500 text-white" : "bg-[var(--accent)] text-white"
        }`}
      >
        {disabled ? <MicOff className="h-4 w-4" aria-hidden /> : <Mic className="h-4 w-4" aria-hidden />}
        {listening ? "Listening — release to stop" : "Hold to talk"}
      </button>
      <p className="text-xs text-[var(--muted)]">
        {reason ?? (shortcut ? `or hold ${shortcut} anywhere` : "Hold the button while speaking")}
      </p>
    </div>
  );
}
