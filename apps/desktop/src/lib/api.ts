import type {
  ApiError,
  AuditEvent,
  BackendConnection,
  HealthReport,
  SystemInfo,
  Task,
  TaskDetail,
  TaskList,
  TaskStatus,
} from "@jack/shared-types";

export class ApiRequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

/** Authenticated client for the loopback JACK service. The token lives only in memory. */
export class JackApi {
  constructor(
    private readonly conn: BackendConnection,
    private readonly fetchImpl: typeof fetch = (...a) => fetch(...a),
  ) {}

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await this.fetchImpl(`${this.conn.baseUrl}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${this.conn.token}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      let code = "http_error";
      let message = `HTTP ${res.status}`;
      try {
        const err = (await res.json()) as ApiError;
        code = err.error.code;
        message = err.error.message;
      } catch {
        /* non-JSON error body */
      }
      throw new ApiRequestError(res.status, code, message);
    }
    return (await res.json()) as T;
  }

  health() {
    return this.request<HealthReport>("GET", "/v1/health");
  }
  systemInfo() {
    return this.request<SystemInfo>("GET", "/v1/system/info");
  }
  listTasks(params: { status?: TaskStatus; limit?: number; offset?: number } = {}) {
    const q = new URLSearchParams();
    if (params.status) q.set("status", params.status);
    q.set("limit", String(params.limit ?? 50));
    q.set("offset", String(params.offset ?? 0));
    return this.request<TaskList>("GET", `/v1/tasks?${q.toString()}`);
  }
  getTask(id: string) {
    return this.request<TaskDetail>("GET", `/v1/tasks/${encodeURIComponent(id)}`);
  }
  createTask(commandText: string, source: "text" | "voice" = "text") {
    return this.request<Task>("POST", "/v1/tasks", { command_text: commandText, source });
  }
  taskAction(id: string, action: "pause" | "resume" | "cancel", reason?: string) {
    return this.request<Task>("POST", `/v1/tasks/${encodeURIComponent(id)}/${action}`, {
      reason: reason ?? null,
    });
  }
  audit(limit = 100, offset = 0) {
    return this.request<{ items: AuditEvent[]; total: number }>(
      "GET",
      `/v1/audit?limit=${limit}&offset=${offset}`,
    );
  }
  verifyAudit() {
    return this.request<{ valid: boolean; checked: number; first_invalid_seq: number | null }>(
      "GET",
      "/v1/audit/verify",
    );
  }
}
