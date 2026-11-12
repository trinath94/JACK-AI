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

export interface ApiError {
  error: { code: string; message: string; request_id: string | null };
}

/** WebSocket server → client envelope (docs/architecture/API_CONTRACTS.md §3). */
export type WsEvent =
  | { type: "event"; topic: "hello"; ts: string; data: { version: string } }
  | { type: "event"; topic: "pong"; ts: string; data: Record<string, never> }
  | { type: "event"; topic: "health.changed"; ts: string;
      data: { status: HealthStatus; components: ComponentHealth[] } }
  | { type: "event"; topic: "task.created" | "task.updated"; ts: string; data: Task };

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
