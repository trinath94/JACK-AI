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
  | { type: "event"; topic: "system.metrics"; ts: string; data: SystemMetrics }
  | { type: "event"; topic: "voice.followup"; ts: string; data: { wait_s: number } }
  | { type: "event"; topic: "discovery.updated"; ts: string; data: { session_id: string; task_id: string; status: DiscoveryStatus } }
  | { type: "event"; topic: "discovery.settings"; ts: string; data: DiscoverySettings };

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

// ------------------------------------------------------------------ requirement discovery (M5)
export type DiscoveryStatus =
  | "choosing_category" | "asking" | "resolving_conflict" | "awaiting_approval" | "changing"
  | "ready" | "cancelled" | "blocked";
export type AnswerSource = "user" | "inferred" | "default";
export type SlotInput = "choice" | "multi" | "text" | "bool";
export type SlotValue = string | string[] | boolean | null;

export interface DiscoverySettings {
  engine: "auto" | "local";
  approval: "auto" | "always";
  followup_listen: boolean;
}

export interface DiscoveryEngineStatus {
  settings: DiscoverySettings;
  using: "claude" | "local";
  detail: string | null;
}

export interface SlotOption { value: string; label: string }

export interface DiscoveryAnswer {
  slot: string;
  label: string;
  input: SlotInput;
  value: SlotValue;
  source: AnswerSource;
  display: string;
  options: SlotOption[];
}

export interface SpecItem {
  slot: string;
  label: string;
  section: string;
  value: SlotValue;
  display: string;
  source: AnswerSource;
}

export interface ProjectSpec {
  version: number;
  title: string;
  category: string;
  category_name: string;
  summary: string;
  requirements: SpecItem[];
  assumptions: SpecItem[];
  open_questions: string[];
  scope: { scale: "small" | "medium" | "large"; components: string[]; rationale: string };
  integrations: { name: string; reason: string }[];
  hosting: { required: boolean; choice: string | null; display: string; source?: string | null };
  dependencies: { capability: string; milestone: number; available: boolean }[];
  engines: string[];
  notes: string[];
  approval_required: boolean;
}

export interface DiscoveryTurn {
  role: "user" | "jack";
  text: string;
  slot: string | null;
  source: string | null;
  at: string;
}

export interface DiscoverySession {
  id: string;
  task_id: string;
  status: DiscoveryStatus;
  category: string | null;
  category_name: string | null;
  category_source: "claude" | "local" | "user" | null;
  command: string;
  question:
    | { kind: "slot"; slot: string; label: string; text: string; input: SlotInput; options: SlotOption[]; default: SlotValue }
    | { kind: "category" | "conflict" | "claude_conflict" | "approval" | "change"; options: SlotOption[] }
    | null;
  answers: DiscoveryAnswer[];
  spec: ProjectSpec | null;
  notes: string[];
  blocked_reason: string | null;
  created_at: string;
  updated_at: string;
  approved_at: string | null;
  turns?: DiscoveryTurn[];
}

export interface DiscoveryReply {
  session_id: string;
  task_id: string;
  text: string;
  status: DiscoveryStatus;
  expects_answer: boolean;
  options: string[];
  slot: string | null;
  listen: boolean;
}

export interface DiscoveryResult {
  reply: DiscoveryReply;
  session: DiscoverySession;
}

export interface DiscoveryCategory { id: string; name: string; description: string; questions: number }
