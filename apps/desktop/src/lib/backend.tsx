import type {
  AIStatus,
  BackendConnection,
  BackendStatus,
  ComponentHealth,
  HealthStatus,
  Notification,
  SpeechModel,
  SystemMetrics,
  Task,
  Utterance,
  VoiceStatus,
  WsEvent,
} from "@jack/shared-types";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiRequestError, JackApi } from "./api";
import { JackSocket, type SocketState } from "./socket";

/** Seam between the UI and Tauri so components can be tested without a native host. */
export interface DesktopBridge {
  isNative: boolean;
  getConnection(): Promise<BackendConnection>;
  getStatus(): Promise<BackendStatus>;
  restart(): Promise<void>;
  onStatus(cb: (s: BackendStatus) => void): Promise<() => void>;
  /** Errors raised by the native push-to-talk hotkey / tray (they bypass the UI). */
  onVoiceError(cb: (message: string) => void): Promise<() => void>;
  syncTray(muted: boolean, voiceState: string): Promise<void>;
  pttShortcut(): Promise<string | null>;
  autostart: {
    supported: boolean;
    isEnabled(): Promise<boolean>;
    set(enabled: boolean): Promise<void>;
  };
}

const NO_AUTOSTART: DesktopBridge["autostart"] = {
  supported: false,
  isEnabled: async () => false,
  set: async () => {},
};

export async function tauriBridge(): Promise<DesktopBridge> {
  const { invoke, isTauri } = await import("@tauri-apps/api/core");
  const { listen } = await import("@tauri-apps/api/event");
  if (!isTauri()) {
    return {
      isNative: false,
      getConnection: () => Promise.reject(new Error("JACK AI must run inside the desktop app")),
      getStatus: async () => ({ state: "stopped", restarts: 0, lastError: "Not running in the desktop app", pid: null }),
      restart: async () => {},
      onStatus: async () => () => {},
      onVoiceError: async () => () => {},
      syncTray: async () => {},
      pttShortcut: async () => null,
      autostart: NO_AUTOSTART,
    };
  }
  const autostart = await import("@tauri-apps/plugin-autostart");
  return {
    isNative: true,
    getConnection: () => invoke<BackendConnection>("backend_connection"),
    getStatus: () => invoke<BackendStatus>("backend_status"),
    restart: () => invoke<void>("restart_backend"),
    onStatus: (cb) => listen<BackendStatus>("backend://status", (e) => cb(e.payload)),
    onVoiceError: (cb) => listen<string>("voice://error", (e) => cb(e.payload)),
    syncTray: (muted, voiceState) => invoke<void>("sync_tray", { muted, voiceState }),
    pttShortcut: () => invoke<string>("ptt_shortcut"),
    autostart: {
      supported: true,
      isEnabled: () => autostart.isEnabled(),
      set: (on) => (on ? autostart.enable() : autostart.disable()),
    },
  };
}

export interface BackendContextValue {
  bridge: DesktopBridge;
  supervisor: BackendStatus;
  socket: SocketState;
  api: JackApi | null;
  health: { status: HealthStatus; components: ComponentHealth[] } | null;
  tasks: Task[];
  voice: VoiceStatus | null;
  voiceLevel: number;
  lastUtterance: Utterance | null;
  /** JACK's most recent spoken (or shown) reply. */
  lastReply: string | null;
  /** Timestamp of the last wake-word detection, for a brief visual cue. */
  wokeAt: number | null;
  models: SpeechModel[];
  refreshModels(): Promise<void>;
  ai: AIStatus | null;
  refreshAI(): Promise<void>;
  voiceError: string | null;
  notifications: Notification[];
  unread: number;
  metrics: SystemMetrics | null;
  /** Monotonic counter bumped on events that change the audit log, for cheap refreshes. */
  activity: number;
  /** Bumped whenever a requirements conversation changes (M5). */
  discoveryTick: number;
  /** When JACK is listening for the answer to its question, without the wake word. */
  followUpUntil: number | null;
  refreshTasks(): Promise<void>;
  refreshVoice(): Promise<void>;
  startPtt(): Promise<void>;
  stopPtt(): Promise<void>;
  markRead(id: string): Promise<void>;
  markAllRead(): Promise<void>;
  clearVoiceError(): void;
  restart(): Promise<void>;
}

const BackendContext = createContext<BackendContextValue | null>(null);

const INITIAL: BackendStatus = { state: "starting", restarts: 0, lastError: null, pid: null };

export function BackendProvider({
  bridge,
  children,
  WebSocketImpl,
}: {
  bridge: DesktopBridge;
  children: ReactNode;
  WebSocketImpl?: typeof WebSocket;
}) {
  const [supervisor, setSupervisor] = useState<BackendStatus>(INITIAL);
  const [conn, setConn] = useState<BackendConnection | null>(null);
  const [socket, setSocket] = useState<SocketState>("closed");
  const [health, setHealth] = useState<BackendContextValue["health"]>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [voice, setVoice] = useState<VoiceStatus | null>(null);
  const [voiceLevel, setVoiceLevel] = useState(0);
  const [lastUtterance, setLastUtterance] = useState<Utterance | null>(null);
  const [lastReply, setLastReply] = useState<string | null>(null);
  const [wokeAt, setWokeAt] = useState<number | null>(null);
  const [models, setModels] = useState<SpeechModel[]>([]);
  const [ai, setAI] = useState<AIStatus | null>(null);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [activity, setActivity] = useState(0);
  const [discoveryTick, setDiscoveryTick] = useState(0);
  const [followUpUntil, setFollowUpUntil] = useState<number | null>(null);
  const connKey = useRef<string | null>(null);

  // Track supervisor state; fetch a new connection whenever the service (re)starts.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let unlistenVoice: (() => void) | undefined;
    let cancelled = false;
    const sync = async (s: BackendStatus) => {
      setSupervisor(s);
      if (s.state !== "running") {
        connKey.current = null;
        setConn(null);
        return;
      }
      try {
        const c = await bridge.getConnection();
        if (cancelled || connKey.current === c.baseUrl + c.token) return;
        connKey.current = c.baseUrl + c.token;
        setConn(c);
      } catch {
        /* a status event will follow */
      }
    };
    void bridge.onStatus((s) => void sync(s)).then((u) => (unlisten = u));
    void bridge.onVoiceError((m) => setVoiceError(m)).then((u) => (unlistenVoice = u));
    void bridge.getStatus().then(sync);
    return () => {
      cancelled = true;
      unlisten?.();
      unlistenVoice?.();
    };
  }, [bridge]);

  const api = useMemo(() => (conn ? new JackApi(conn) : null), [conn]);

  const refreshTasks = useCallback(async () => {
    if (!api) return;
    const list = await api.listTasks({ limit: 50 });
    setTasks(list.items);
  }, [api]);

  const refreshVoice = useCallback(async () => {
    if (!api) return;
    setVoice(await api.voiceStatus());
  }, [api]);

  const refreshModels = useCallback(async () => {
    if (!api) return;
    setModels(await api.speechModels());
  }, [api]);

  const refreshAI = useCallback(async () => {
    if (!api) return;
    setAI(await api.aiStatus());
  }, [api]);

  const refreshNotifications = useCallback(async () => {
    if (!api) return;
    const list = await api.notifications(false, 50);
    setNotifications(list.items);
    setUnread(list.unread);
  }, [api]);

  useEffect(() => {
    if (!conn || !api) {
      setHealth(null);
      setVoice(null);
      setMetrics(null);
      return;
    }
    void refreshTasks().catch(() => {});
    void refreshVoice().catch(() => {});
    void refreshNotifications().catch(() => {});
    void refreshModels().catch(() => {});
    void refreshAI().catch(() => {});
    void api.metrics().then(setMetrics).catch(() => {});
    const onEvent = (e: WsEvent) => {
      switch (e.topic) {
        case "health.changed":
          setHealth(e.data);
          break;
        case "task.created":
        case "task.updated":
          setTasks((prev) => [e.data, ...prev.filter((t) => t.id !== e.data.id)].slice(0, 50));
          setActivity((n) => n + 1);
          break;
        case "voice.state":
          setVoice((v) => (v ? { ...v, state: e.data.state } : v));
          if (e.data.state !== "listening") setVoiceLevel(0);
          setActivity((n) => n + 1);
          break;
        case "voice.level":
          setVoiceLevel(e.data.level);
          break;
        case "voice.settings":
          setVoice((v) => (v ? { ...v, settings: e.data } : v));
          break;
        case "voice.utterance":
          setLastUtterance(e.data);
          setActivity((n) => n + 1);
          break;
        case "voice.reply":
          setLastReply(e.data.text);
          break;
        case "voice.wake":
          setWokeAt(Date.now());
          setActivity((n) => n + 1);
          break;
        case "voice.models":
          setModels(e.data);
          // Capabilities depend on which models are present.
          void refreshVoice().catch(() => {});
          break;
        case "voice.error":
          setVoiceError(e.data.message);
          break;
        case "notification.created":
          setNotifications((prev) => [e.data, ...prev].slice(0, 50));
          setUnread((n) => n + 1);
          break;
        case "notification.read": {
          const ids = new Set(e.data.ids);
          setNotifications((prev) =>
            prev.map((n) => (ids.has(n.id) && !n.read_at ? { ...n, read_at: e.ts } : n)),
          );
          // The server owns the unread count; refetch rather than guess.
          void refreshNotifications().catch(() => {});
          break;
        }
        case "system.metrics":
          setMetrics(e.data);
          break;
        case "ai.status":
        case "ai.usage":
          void refreshAI().catch(() => {});
          setActivity((n) => n + 1);
          break;
        case "discovery.updated":
        case "discovery.settings":
          setDiscoveryTick((n) => n + 1);
          setActivity((n) => n + 1);
          break;
        case "voice.followup":
          setFollowUpUntil(Date.now() + e.data.wait_s * 1000);
          break;
      }
    };
    const s = new JackSocket(conn, { onEvent, onState: setSocket, WebSocketImpl });
    s.start();
    return () => s.stop();
  }, [conn, api, refreshTasks, refreshVoice, refreshNotifications, refreshModels, refreshAI, WebSocketImpl]);

  // Keep the tray tooltip / mute checkbox in step with the service.
  const voiceStateKey = voice ? `${voice.settings.muted}|${voice.state}` : null;
  useEffect(() => {
    if (!voice) return;
    void bridge.syncTray(voice.settings.muted, voice.state).catch(() => {});
  }, [bridge, voiceStateKey]);

  const runVoice = useCallback(
    async (fn: (a: JackApi) => Promise<unknown>) => {
      if (!api) return;
      try {
        setVoiceError(null);
        await fn(api);
      } catch (err) {
        setVoiceError(err instanceof ApiRequestError ? err.message : "Voice action failed");
      }
    },
    [api],
  );

  const value: BackendContextValue = {
    bridge,
    supervisor,
    socket,
    api,
    health,
    tasks,
    voice,
    voiceLevel,
    lastUtterance,
    lastReply,
    wokeAt,
    models,
    refreshModels,
    ai,
    refreshAI,
    voiceError,
    notifications,
    unread,
    metrics,
    activity,
    discoveryTick,
    followUpUntil,
    refreshTasks,
    refreshVoice,
    startPtt: () => runVoice((a) => a.pttStart("ui")),
    stopPtt: () => runVoice((a) => a.pttStop()),
    markRead: async (id) => {
      await api?.markNotificationRead(id);
    },
    markAllRead: async () => {
      await api?.markAllNotificationsRead();
    },
    clearVoiceError: () => setVoiceError(null),
    restart: () => bridge.restart(),
  };
  return <BackendContext.Provider value={value}>{children}</BackendContext.Provider>;
}

export function useBackend(): BackendContextValue {
  const v = useContext(BackendContext);
  if (!v) throw new Error("useBackend must be used inside <BackendProvider>");
  return v;
}
