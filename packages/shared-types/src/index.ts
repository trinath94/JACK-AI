/**
 * Contract types for the JACK local service.
 * `api.gen.ts` is generated from services/api's OpenAPI schema by `pnpm gen:types`;
 * CI fails if it is out of date. Do not edit it by hand.
 */
import type { components } from "./api.gen";

type Schemas = components["schemas"];

export type HealthReport = Schemas["HealthReport"];
export type ComponentHealth = Schemas["ComponentHealthOut"];
export type HealthStatus = HealthReport["status"];
export type SystemInfo = Schemas["SystemInfo"];
export type Task = Schemas["TaskOut"];
export type TaskDetail = Schemas["TaskDetail"];
export type TaskList = Schemas["TaskList"];
export type TaskStatus = Schemas["TaskStatus"];
export type TaskCreate = Schemas["TaskCreate"];
export type AuditEvent = Schemas["AuditEventOut"];
export type VoiceStatus = Schemas["VoiceStatus"];
export type VoiceState = VoiceStatus["state"];
export type VoiceSettings = Schemas["VoiceSettings"];
export type VoiceSettingsPatch = Schemas["VoiceSettingsPatch"];
export type VoiceCapabilities = Schemas["VoiceCapabilities"];
export type AudioDevice = Schemas["AudioDeviceOut"];
export type PttStopped = Schemas["PttStoppedOut"];
export type SpeechModel = Schemas["SpeechModelOut"];
export type TtsVoice = Schemas["TtsVoiceOut"];
export type VoiceSession = Schemas["SessionOut"];
export type VoiceHistory = Schemas["HistoryOut"];

/** Payload of the `voice.utterance` event: one completed voice interaction. */
export interface Utterance {
  trigger: "ptt" | "wake";
  captured_ms: number;
  transcribed: boolean;
  transcript: string | null;
  reply: string;
  stopped_by: string;
  task_id: string | null;
}
export type Notification = Schemas["NotificationOut"];
export type NotificationList = Schemas["NotificationList"];
export type SystemMetrics = Schemas["SystemMetricsOut"];

export interface ApiError {
  error: { code: string; message: string; request_id: string | null };
}

/** WebSocket server → client envelope (docs/architecture/API_CONTRACTS.md §3). */
export type WsEvent =
  | { type: "event"; topic: "hello"; ts: string; data: { version: string } }
  | { type: "event"; topic: "pong"; ts: string; data: Record<string, never> }
  | { type: "event"; topic: "health.changed"; ts: string;
      data: { status: HealthStatus; components: ComponentHealth[] } }
  | { type: "event"; topic: "task.created" | "task.updated"; ts: string; data: Task }
  | { type: "event"; topic: "voice.state"; ts: string; data: { state: VoiceState } }
  | { type: "event"; topic: "voice.level"; ts: string; data: { level: number } }
  | { type: "event"; topic: "voice.settings"; ts: string; data: VoiceSettings }
  | { type: "event"; topic: "voice.utterance"; ts: string; data: Utterance }
  | { type: "event"; topic: "voice.wake"; ts: string; data: { transcript: string } }
  | { type: "event"; topic: "voice.reply"; ts: string; data: { text: string } }
  | { type: "event"; topic: "voice.models"; ts: string; data: SpeechModel[] }
  | { type: "event"; topic: "ai.status"; ts: string; data: { changed: string } }
  | { type: "event"; topic: "ai.usage"; ts: string; data: { provider: string; cost_usd?: string | null; failed?: string } }
  | { type: "event"; topic: "voice.error"; ts: string; data: { code: string; message: string } }
  | { type: "event"; topic: "notification.created"; ts: string; data: Notification }
  | { type: "event"; topic: "notification.read"; ts: string; data: { ids: string[] } }
  | { type: "event"; topic: "system.metrics"; ts: string; data: SystemMetrics };

/** Rust supervisor types (apps/desktop/src-tauri/src/supervisor.rs). */
export type BackendState = "starting" | "running" | "restarting" | "failed" | "stopped";
export interface BackendStatus {
  state: BackendState;
  restarts: number;
  lastError: string | null;
  pid: number | null;
}
export interface BackendConnection {
  baseUrl: string;
  wsUrl: string;
  token: string;
}

/* ------------------------------------------------------------------ AI providers (M4)
 * The /v1/ai routes return untyped JSON in the OpenAPI schema; these interfaces mirror
 * services/api/src/jack_api/ai/service.py. */
export type AIProviderId = "anthropic" | "claude_code";
export type AIEffort = "low" | "medium" | "high" | "xhigh" | "max";

export interface AITestResult {
  ok: boolean;
  at: string;
  model: string | null;
  latency_ms: number | null;
  reply: string | null;
  error: string | null;
  error_code: string | null;
}

export interface UsageBucket {
  requests: number;
  failed: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost_usd: string;
  unpriced_requests: number;
}

export interface MonthSummary {
  month: string;
  api: UsageBucket;
  claude_code: UsageBucket;
  by_model: { model: string; billing_kind: "api" | "claude_code"; input_tokens: number; output_tokens: number; cost_usd: string }[];
  by_day: { day: string; cost_usd: string }[];
  monthly_limit_usd: string | null;
  limit_used_pct: number | null;
}

export interface AIStatus {
  credential_store: { kind: string; secure: boolean; available: boolean; detail: string | null };
  anthropic: {
    configured: boolean;
    key_hint: string | null;
    settings: { model: string; effort: AIEffort | null; timeout_s: number; max_retries: number; refusal_fallback: boolean };
    last_test: AITestResult | null;
    price_known: boolean;
  };
  claude_code: {
    settings: { enabled: boolean; binary: string | null; model: string | null; timeout_s: number };
    detected: ClaudeCodeDetection | null;
    last_test: AITestResult | null;
  };
  routing: { reasoning: AIProviderId; coding: AIProviderId };
  fallback: { enabled: boolean };
  limits: { monthly_usd: string | null; per_task_usd: string | null; per_project_usd: string | null; alert_pct: number[] };
  prices_as_of: string;
  month: MonthSummary;
}

export interface ClaudeCodeDetection {
  installed: boolean;
  binary: string | null;
  version: string | null;
  logged_in: boolean;
  auth_method: string | null;
  api_provider: string | null;
  detail: string | null;
}

export interface AIModel {
  id: string;
  display_name: string;
  max_input_tokens: number | null;
  max_tokens: number | null;
  price_known: boolean;
}

export interface AICompletion {
  text: string;
  provider: AIProviderId;
  model_requested: string;
  model_served: string;
  stop_reason: string | null;
  billing_kind: "api" | "claude_code";
  latency_ms: number;
  refusal_category: string | null;
  fallbacks: [string, string][];
  usage: { model: string; input_tokens: number; output_tokens: number; cache_read: number; cache_write_5m: number; cache_write_1h: number }[];
  cost_usd: string | null;
  reported_cost_usd: string | null;
}

export interface UsageRecordRow {
  id: string;
  occurred_at: string;
  provider: AIProviderId;
  billing_kind: "api" | "claude_code";
  model: string;
  purpose: string;
  task_id: string | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string | null;
  cost_source: string;
  succeeded: boolean;
  error_code: string | null;
  latency_ms: number | null;
}

export interface AISettingsPatch {
  anthropic?: Partial<AIStatus["anthropic"]["settings"]>;
  claude_code?: Partial<AIStatus["claude_code"]["settings"]>;
  routing?: Partial<AIStatus["routing"]>;
  fallback?: Partial<AIStatus["fallback"]>;
  limits?: Partial<{ monthly_usd: string | null; per_task_usd: string | null; per_project_usd: string | null; alert_pct: number[] }>;
}
