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
export type PttResult = Schemas["PttResultOut"];
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
  | { type: "event"; topic: "voice.utterance"; ts: string; data: PttResult }
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
