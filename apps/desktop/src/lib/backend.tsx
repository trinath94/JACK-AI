import type {
  BackendConnection,
  BackendStatus,
  ComponentHealth,
  HealthStatus,
  Task,
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
import { JackApi } from "./api";
import { JackSocket, type SocketState } from "./socket";

/** Seam between the UI and Tauri so components can be tested without a native host. */
export interface DesktopBridge {
  isNative: boolean;
  getConnection(): Promise<BackendConnection>;
  getStatus(): Promise<BackendStatus>;
  restart(): Promise<void>;
  onStatus(cb: (s: BackendStatus) => void): Promise<() => void>;
}

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
    };
  }
  return {
    isNative: true,
    getConnection: () => invoke<BackendConnection>("backend_connection"),
    getStatus: () => invoke<BackendStatus>("backend_status"),
    restart: () => invoke<void>("restart_backend"),
    onStatus: (cb) => listen<BackendStatus>("backend://status", (e) => cb(e.payload)),
  };
}

export interface BackendContextValue {
  supervisor: BackendStatus;
  socket: SocketState;
  api: JackApi | null;
  health: { status: HealthStatus; components: ComponentHealth[] } | null;
  tasks: Task[];
  refreshTasks(): Promise<void>;
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
  const connKey = useRef<string | null>(null);

  // Track supervisor state; fetch a new connection whenever the service (re)starts.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
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
    void bridge.getStatus().then(sync);
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [bridge]);

  const api = useMemo(() => (conn ? new JackApi(conn) : null), [conn]);

  const refreshTasks = useCallback(async () => {
    if (!api) return;
    const list = await api.listTasks({ limit: 50 });
    setTasks(list.items);
  }, [api]);

  useEffect(() => {
    if (!conn) {
      setHealth(null);
      return;
    }
    void refreshTasks().catch(() => {});
    const onEvent = (e: WsEvent) => {
      if (e.topic === "health.changed") setHealth(e.data);
      if (e.topic === "task.created" || e.topic === "task.updated") {
        setTasks((prev) => [e.data, ...prev.filter((t) => t.id !== e.data.id)].slice(0, 50));
      }
    };
    const s = new JackSocket(conn, { onEvent, onState: setSocket, WebSocketImpl });
    s.start();
    return () => s.stop();
  }, [conn, refreshTasks, WebSocketImpl]);

  const value: BackendContextValue = {
    supervisor,
    socket,
    api,
    health,
    tasks,
    refreshTasks,
    restart: () => bridge.restart(),
  };
  return <BackendContext.Provider value={value}>{children}</BackendContext.Provider>;
}

export function useBackend(): BackendContextValue {
  const v = useContext(BackendContext);
  if (!v) throw new Error("useBackend must be used inside <BackendProvider>");
  return v;
}
