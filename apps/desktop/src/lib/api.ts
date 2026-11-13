import type {
  AICompletion,
  AIModel,
  AIProviderId,
  AISettingsPatch,
  AIStatus,
  AITestResult,
  ApiError,
  ClaudeCodeDetection,
  MonthSummary,
  UsageRecordRow,
  AuditEvent,
  BackendConnection,
  AudioDevice,
  HealthReport,
  NotificationList,
  PttStopped,
  SpeechModel,
  SystemInfo,
  SystemMetrics,
  Task,
  TaskDetail,
  TaskList,
  TaskStatus,
  TtsVoice,
  VoiceHistory,
  VoiceSettings,
  VoiceSettingsPatch,
  VoiceStatus,
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
    if (res.status === 204) return undefined as T;
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
  voiceStatus() {
    return this.request<VoiceStatus>("GET", "/v1/voice/status");
  }
  voiceDevices() {
    return this.request<AudioDevice[]>("GET", "/v1/voice/devices");
  }
  updateVoiceSettings(patch: VoiceSettingsPatch) {
    return this.request<VoiceSettings>("PATCH", "/v1/voice/settings", patch);
  }
  pttStart(source: "ui" | "hotkey" | "tray" = "ui") {
    return this.request<VoiceStatus>("POST", "/v1/voice/ptt/start", { source });
  }
  pttStop() {
    return this.request<PttStopped | null>("POST", "/v1/voice/ptt/stop");
  }
  speechModels() {
    return this.request<SpeechModel[]>("GET", "/v1/voice/models");
  }
  downloadSpeechModel(name: string) {
    return this.request<{ started: boolean }>("POST", `/v1/voice/models/${encodeURIComponent(name)}/download`);
  }
  deleteSpeechModel(name: string) {
    return this.request<void>("DELETE", `/v1/voice/models/${encodeURIComponent(name)}`);
  }
  ttsVoices() {
    return this.request<TtsVoice[]>("GET", "/v1/voice/voices");
  }
  speak(text: string) {
    return this.request<{ queued: boolean }>("POST", "/v1/voice/speak", { text });
  }
  stopSpeaking() {
    return this.request<{ stopped: boolean }>("POST", "/v1/voice/stop-speaking");
  }
  voiceHistory(limit = 30) {
    return this.request<VoiceHistory>("GET", `/v1/voice/history?limit=${limit}`);
  }
  clearVoiceHistory() {
    return this.request<{ deleted: number }>("DELETE", "/v1/voice/history");
  }
  notifications(unreadOnly = false, limit = 50) {
    return this.request<NotificationList>(
      "GET",
      `/v1/notifications?unread_only=${unreadOnly}&limit=${limit}`,
    );
  }
  markNotificationRead(id: string) {
    return this.request<void>("POST", `/v1/notifications/${encodeURIComponent(id)}/read`);
  }
  markAllNotificationsRead() {
    return this.request<{ marked: number }>("POST", "/v1/notifications/read-all");
  }
  metrics() {
    return this.request<SystemMetrics>("GET", "/v1/system/metrics");
  }
  aiStatus() {
    return this.request<AIStatus>("GET", "/v1/ai/status");
  }
  setAnthropicKey(apiKey: string) {
    return this.request<void>("PUT", "/v1/ai/anthropic/key", { api_key: apiKey });
  }
  deleteAnthropicKey() {
    return this.request<void>("DELETE", "/v1/ai/anthropic/key");
  }
  updateAISettings(patch: AISettingsPatch) {
    return this.request<unknown>("PATCH", "/v1/ai/settings", patch);
  }
  anthropicModels(refresh = false) {
    return this.request<AIModel[]>("GET", `/v1/ai/anthropic/models?refresh=${refresh}`);
  }
  testProvider(provider: AIProviderId) {
    return this.request<AITestResult>("POST", `/v1/ai/${provider}/test`);
  }
  detectClaudeCode() {
    return this.request<ClaudeCodeDetection>("POST", "/v1/ai/claude-code/detect");
  }
  aiComplete(prompt: string, provider?: AIProviderId) {
    return this.request<AICompletion>("POST", "/v1/ai/complete", { prompt, ...(provider ? { provider } : {}) });
  }
  aiUsage(month?: string) {
    return this.request<MonthSummary>("GET", `/v1/ai/usage${month ? `?month=${month}` : ""}`);
  }
  aiUsageRecords(limit = 20) {
    return this.request<{ items: UsageRecordRow[]; total: number }>("GET", `/v1/ai/usage/records?limit=${limit}`);
  }
  verifyAudit() {
    return this.request<{ valid: boolean; checked: number; first_invalid_seq: number | null }>(
      "GET",
      "/v1/audit/verify",
    );
  }
}
