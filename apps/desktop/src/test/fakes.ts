import type {
  AIStatus,
  BackendConnection,
  BackendStatus,
  Notification,
  SpeechModel,
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
    asr_model: "small.en",
    end_of_speech_ms: 800,
    tts_enabled: true,
    tts_voice_id: null,
    tts_rate: 1,
    keep_history: true,
    history_retention_days: 30,
  },
  capabilities: {
    capture: true,
    capture_detail: null,
    wake_word: true,
    wake_word_detail: null,
    wake_word_engine: "keyword-asr",
    speech_recognition: true,
    speech_recognition_detail: null,
    speech_synthesis: true,
    speech_synthesis_detail: null,
    speech_synthesis_engine: "sapi",
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

const EMPTY_BUCKET = { requests: 0, failed: 0, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0, cost_usd: "0", unpriced_requests: 0 };

export function aiStatus(): AIStatus {
  return {
    credential_store: { kind: "keyring.backends.Windows.WinVaultKeyring", secure: true, available: true, detail: null },
    anthropic: {
      configured: false,
      key_hint: null,
      settings: { model: "claude-opus-5-5", effort: "medium", timeout_s: 120, max_retries: 2, refusal_fallback: true },
      last_test: null,
      price_known: true,
    },
    claude_code: { settings: { enabled: false, binary: null, model: null, timeout_s: 300 }, detected: null, last_test: null },
    routing: { reasoning: "anthropic", coding: "claude_code" },
    fallback: { enabled: false },
    limits: { monthly_usd: null, per_task_usd: null, per_project_usd: null, alert_pct: [50, 80, 100] },
    prices_as_of: "2026-11-03",
    month: { month: "2026-11", api: { ...EMPTY_BUCKET }, claude_code: { ...EMPTY_BUCKET }, by_model: [], by_day: [], monthly_limit_usd: null, limit_used_pct: null },
  };
}

/** In-memory stand-in for the JACK service REST API. */
export const MODELS: SpeechModel[] = [
  { name: "tiny.en", size_mb: 75, purpose: "Wake word", status: "ready", downloaded_mb: 0, error: null },
  { name: "base.en", size_mb: 145, purpose: "Commands on slower PCs", status: "not_downloaded", downloaded_mb: 0, error: null },
  { name: "small.en", size_mb: 484, purpose: "Commands (recommended accuracy)", status: "ready", downloaded_mb: 0, error: null },
];

export function mockService(init: { voice?: VoiceStatus; notifications?: Notification[] } = {}) {
  const state = {
    ai: aiStatus(),
    models: structuredClone(MODELS),
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
    if (path === "/v1/voice/ptt/stop") return json(200, { captured_ms: 1500, stopped_by: "released", processing: true });
    if (path === "/v1/voice/models") return json(200, state.models);
    if (/^\/v1\/voice\/models\/[^/]+\/download$/.test(path)) {
      const m = state.models.find((x) => x.name === path.split("/")[4]);
      if (m) m.status = "downloading";
      return json(202, { started: true });
    }
    if (path === "/v1/voice/voices") return json(200, [{ id: "zira", name: "Microsoft Zira", language: "en-US" }]);
    if (path === "/v1/voice/speak") return json(202, { queued: true });
    if (path === "/v1/voice/stop-speaking") return json(200, { stopped: true });
    if (path.startsWith("/v1/voice/history") && method === "DELETE") return json(200, { deleted: 1 });
    if (path.startsWith("/v1/voice/history"))
      return json(200, { items: [{ id: "s1", trigger: "wake", started_at: "2026-11-12T10:00:00Z", ended_at: null, task_id: "t1", turns: [{ role: "user", text: "build a website", created_at: "2026-11-12T10:00:00Z" }, { role: "jack", text: "Got it.", created_at: "2026-11-12T10:00:01Z" }] }], total: 1 });
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
    if (path === "/v1/ai/status") return json(200, state.ai);
    if (path === "/v1/ai/anthropic/key" && method === "PUT") {
      state.ai.anthropic.configured = true;
      state.ai.anthropic.key_hint = `sk-ant-…${String((body as { api_key: string }).api_key).slice(-4)}`;
      return json(204, undefined);
    }
    if (path === "/v1/ai/anthropic/key" && method === "DELETE") {
      state.ai.anthropic.configured = false;
      state.ai.anthropic.key_hint = null;
      return json(204, undefined);
    }
    if (path === "/v1/ai/settings") {
      const p = body as Record<string, Record<string, unknown>>;
      for (const [k, v] of Object.entries(p)) Object.assign((state.ai as unknown as Record<string, object>)[k]!, v);
      return json(200, {});
    }
    if (path.startsWith("/v1/ai/anthropic/models"))
      return json(200, [{ id: "claude-opus-5-5", display_name: "Claude Opus 5.5", max_input_tokens: 1e6, max_tokens: 128000, price_known: true },
        { id: "claude-future-9", display_name: "Claude Future 9", max_input_tokens: null, max_tokens: null, price_known: false }]);
    if (path === "/v1/ai/anthropic/test") {
      state.ai.anthropic.last_test = { ok: true, at: "2026-11-12T10:00:00Z", model: "claude-opus-5-5", latency_ms: 420, reply: "OK", error: null, error_code: null };
      return json(200, state.ai.anthropic.last_test);
    }
    if (path === "/v1/ai/claude-code/detect") {
      state.ai.claude_code.detected = { installed: true, binary: "C:/claude.cmd", version: "2.1.322 (Claude Code)", logged_in: true, auth_method: "claude.ai", api_provider: "firstParty", detail: null };
      return json(200, state.ai.claude_code.detected);
    }
    if (path === "/v1/ai/complete")
      return json(200, { text: "Hello from Claude", provider: "anthropic", model_requested: "claude-opus-5-5", model_served: "claude-opus-5-5", stop_reason: "end_turn", billing_kind: "api", latency_ms: 812, refusal_category: null, fallbacks: [], usage: [{ model: "claude-opus-5-5", input_tokens: 20, output_tokens: 6, cache_read: 0, cache_write_5m: 0, cache_write_1h: 0 }], cost_usd: "0.000200", reported_cost_usd: null });
    if (path.startsWith("/v1/ai/usage/records")) return json(200, { items: [], total: 0 });
    if (path.startsWith("/v1/audit?")) return json(200, { items: [], total: 0 });
    if (path === "/v1/system/info") return json(404, {});
    return json(404, { error: { code: "not_found", message: path, request_id: null } });
  };
  return { state, fetchImpl };
}
