import type {
  BackendConnection,
  BackendStatus,
  Notification,
  SystemMetrics,
  VoiceStatus,
} from "@jack/shared-types";
import type { DesktopBridge } from "../lib/backend";

export const CONN: BackendConnection = {
  baseUrl: "http://127.0.0.1:5555",
  wsUrl: "ws://127.0.0.1:5555/v1/ws",
  token: "t".repeat(64),
};

export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  // test helpers
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  emit(topic: string, data: unknown) {
    this.onmessage?.({ data: JSON.stringify({ type: "event", topic, ts: new Date().toISOString(), data }) });
  }
  drop() {
    this.readyState = 3;
    this.onclose?.();
  }
}

export type FakeBridge = DesktopBridge & {
  push: (s: BackendStatus) => void;
  voiceError: (m: string) => void;
  trayCalls: Array<[boolean, string]>;
  autostartOn: boolean;
};

export function fakeBridge(status: BackendStatus["state"] = "running"): FakeBridge {
  let listener: ((s: BackendStatus) => void) | null = null;
  let voiceListener: ((m: string) => void) | null = null;
  const current: BackendStatus = { state: status, restarts: 0, lastError: null, pid: 42 };
  const bridge: FakeBridge = {
    isNative: true,
    getConnection: async () => CONN,
    getStatus: async () => current,
    restart: async () => {},
    onStatus: async (cb) => {
      listener = cb;
      return () => (listener = null);
    },
    onVoiceError: async (cb) => {
      voiceListener = cb;
      return () => (voiceListener = null);
    },
    syncTray: async (muted, state) => {
      bridge.trayCalls.push([muted, state]);
    },
    pttShortcut: async () => "Ctrl+Shift+Space",
    autostart: {
      supported: true,
      isEnabled: async () => bridge.autostartOn,
      set: async (on) => {
        bridge.autostartOn = on;
      },
    },
    push: (s) => listener?.(s),
    voiceError: (m) => voiceListener?.(m),
    trayCalls: [],
    autostartOn: false,
  };
  return bridge;
}

export const VOICE: VoiceStatus = {
  state: "idle",
  settings: {
    wake_word_enabled: false,
    wake_word_sensitivity: 0.5,
    input_device_id: null,
    muted: false,
    privacy_mode: false,
    max_listen_s: 30,
  },
  capabilities: {
    capture: true,
    capture_detail: null,
    wake_word: false,
    speech_recognition: false,
    speech_synthesis: false,
    pending_milestone: 3,
  },
  listening_since_s: null,
};

export const METRICS: SystemMetrics = {
  cpu_percent: 12.5,
  cpu_count: 8,
  memory_total_bytes: 16 * 1024 ** 3,
  memory_used_bytes: 6 * 1024 ** 3,
  memory_percent: 37.5,
  disk_total_bytes: 512 * 1024 ** 3,
  disk_free_bytes: 200 * 1024 ** 3,
  disk_percent: 61,
  service_rss_bytes: 80 * 1024 ** 2,
  service_cpu_percent: 1,
  uptime_s: 3600,
};

export const TASK = {
  id: "11111111-1111-1111-1111-111111111111",
  title: "Build a corporate website",
  command_text: "Build a corporate website",
  source: "text",
  status: "RECEIVED",
  status_reason: null,
  mode: "assisted",
  created_at: "2026-11-12T10:00:00Z",
  updated_at: "2026-11-12T10:00:00Z",
  completed_at: null,
};

/** In-memory stand-in for the JACK service REST API. */
export function mockService(init: { voice?: VoiceStatus; notifications?: Notification[] } = {}) {
  const state = {
    voice: structuredClone(init.voice ?? VOICE),
    notifications: structuredClone(init.notifications ?? []) as Notification[],
    pttError: null as null | { code: string; message: string },
    calls: [] as Array<{ method: string; path: string; body: unknown }>,
  };
  const json = (status: number, body: unknown) =>
    new Response(body === undefined ? null : JSON.stringify(body), { status });
  const fetchImpl = async (url: string, init?: RequestInit) => {
    const path = url.replace(CONN.baseUrl, "");
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    state.calls.push({ method, path, body });
    if (path === "/v1/tasks" && method === "POST") return json(201, TASK);
    if (path.startsWith("/v1/tasks?")) return json(200, { items: [], total: 0 });
    if (path.startsWith("/v1/tasks/")) return json(200, { ...TASK, events: [] });
    if (path === "/v1/voice/status") return json(200, state.voice);
    if (path === "/v1/voice/devices")
      return json(200, [{ id: "WASAPI:Headset", name: "Headset", host_api: "WASAPI", is_default: true, channels: 1 }]);
    if (path === "/v1/voice/settings" && method === "PATCH") {
      state.voice.settings = { ...state.voice.settings, ...body };
      return json(200, state.voice.settings);
    }
    if (path === "/v1/voice/ptt/start") {
      if (state.pttError) return json(409, { error: { ...state.pttError, request_id: null } });
      return json(200, { ...state.voice, state: "listening" });
    }
    if (path === "/v1/voice/ptt/stop")
      return json(200, { captured_ms: 1500, transcribed: false, transcript: null, detail: "Speech recognition arrives in Milestone 3; the captured audio was discarded.", stopped_by: "released" });
    if (path.startsWith("/v1/notifications?"))
      return json(200, { items: state.notifications, total: state.notifications.length, unread: state.notifications.filter((n) => !n.read_at).length });
    if (path === "/v1/notifications/read-all") {
      const n = state.notifications.filter((x) => !x.read_at).length;
      state.notifications.forEach((x) => (x.read_at ??= "2026-11-12T10:00:00Z"));
      return json(200, { marked: n });
    }
    if (/^\/v1\/notifications\/[^/]+\/read$/.test(path)) {
      const id = decodeURIComponent(path.split("/")[3]!);
      state.notifications.forEach((x) => x.id === id && (x.read_at ??= "2026-11-12T10:00:00Z"));
      return json(204, undefined);
    }
    if (path === "/v1/system/metrics") return json(200, METRICS);
    if (path.startsWith("/v1/audit?")) return json(200, { items: [], total: 0 });
    if (path === "/v1/system/info") return json(404, {});
    return json(404, { error: { code: "not_found", message: path, request_id: null } });
  };
  return { state, fetchImpl };
}
