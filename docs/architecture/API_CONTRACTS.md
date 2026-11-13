# JACK AI — Local Service API Contracts

Deliverable 5 of Section 30. Base URL: `http://127.0.0.1:<port>` (loopback only).
The machine-readable contract is the OpenAPI document served at `/v1/openapi.json`
(authenticated). Routes marked **M1** are implemented and tested.

## 1. Authentication

| Requirement | Applies to |
|---|---|
| `Authorization: Bearer <session token>` | every route except `/health/live` |
| `Host` ∈ {`127.0.0.1:<port>`, `localhost:<port>`} | every route |
| WebSocket first frame `{"type":"auth","token":"…"}` within 5 s | `/v1/ws` |

Errors use one envelope:

```json
{ "error": { "code": "unauthorized", "message": "Missing or invalid session token", "request_id": "…" } }
```

Codes: `unauthorized` 401, `forbidden_host` 421, `not_found` 404, `validation_error` 422,
`invalid_transition` 409, `internal` 500.

## 2. Routes

### Health — M1
| Method | Path | Auth | Response |
|---|---|---|---|
| GET | `/health/live` | none | `{"status":"ok"}` |
| GET | `/v1/health` | yes | `HealthReport` |

```json
HealthReport = {
  "status": "healthy" | "degraded" | "unhealthy",
  "version": "0.1.0",
  "uptime_s": 12.3,
  "components": [ { "name": "database", "status": "healthy", "detail": null, "latency_ms": 1.2, "checked_at": "…" } ]
}
```

### System — M1
| GET | `/v1/system/info` | yes | `{ app_version, python_version, platform, data_dir, database_backend, pid }` |

### Tasks — M1 (persistence + state machine; execution arrives in M6)
| Method | Path | Body / Query | Response |
|---|---|---|---|
| POST | `/v1/tasks` | `{ "command_text": str(1..4000), "source": "text"|"voice", "title"?: str }` | 201 `Task` |
| GET | `/v1/tasks` | `?status=&limit=50&offset=0` | `{ "items": Task[], "total": int }` |
| GET | `/v1/tasks/{id}` | – | `Task` with `events: TaskEvent[]` |
| POST | `/v1/tasks/{id}/transition` | `{ "to_status": TaskStatus, "reason"?: str }` | `Task` · 409 `invalid_transition` |
| POST | `/v1/tasks/{id}/pause` · `/resume` · `/cancel` | `{ "reason"?: str }` | `Task` |

```json
Task = { "id": "uuid", "title": "…", "command_text": "…", "source": "text", "status": "RECEIVED",
         "status_reason": null, "mode": "assisted", "created_at": "…", "updated_at": "…", "completed_at": null }
TaskEvent = { "seq": 1, "from_status": null, "to_status": "RECEIVED", "reason": "created", "actor": "user", "occurred_at": "…" }
```

### Audit — M1
| GET | `/v1/audit` | `?limit=100&offset=0` | `{ items: AuditEvent[], total }` |
| GET | `/v1/audit/verify` | – | `{ "valid": bool, "checked": int, "first_invalid_seq": int|null }` |

### Voice — M2 + M3
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/v1/voice/status` | – | `{ state, settings, capabilities{capture, capture_detail, wake_word, speech_recognition, speech_synthesis, pending_milestone}, listening_since_s }` |
| GET | `/v1/voice/devices` | – | `[{ id: "<host api>:<name>", name, host_api, is_default, channels }]` |
| PATCH | `/v1/voice/settings` | any of `wake_word_enabled, wake_word_sensitivity (0.1–0.9), input_device_id, muted, privacy_mode, max_listen_s (5–120)` | `VoiceSettings` · 409 `unknown_device` |
| POST | `/v1/voice/ptt/start` | `{ "source": "ui"|"hotkey"|"tray" }` | `VoiceStatus` · 409 `muted` / `privacy_mode` / `unknown_device` / `audio_unavailable` |
| POST | `/v1/voice/ptt/stop` | – | `{ captured_ms, stopped_by, processing: true }` or `null`; the result arrives as `voice.utterance` |
| GET | `/v1/voice/voices` | – | `[{ id, name, language }]` (Windows SAPI voices) |
| POST | `/v1/voice/speak` | `{ text (1–500) }` | 202 — interrupts with push-to-talk or `/stop-speaking` |
| POST | `/v1/voice/stop-speaking` | – | `{ stopped }` |
| GET | `/v1/voice/models` | – | `[{ name, size_mb, purpose, status: not_downloaded|downloading|ready|error, downloaded_mb, error }]` |
| POST | `/v1/voice/models/{name}/download` | – | 202 `{ started }` — the only way models are fetched |
| DELETE | `/v1/voice/models/{name}` | – | 204 |
| GET / DELETE | `/v1/voice/history` | `?limit&offset` | `{ items: [{ id, trigger, started_at, ended_at, task_id, turns:[{role,text,created_at}] }], total }` / `{ deleted }` |

Settings added in M3: `asr_model`, `end_of_speech_ms`, `tts_enabled`, `tts_voice_id`, `tts_rate`,
`keep_history`, `history_retention_days`. States added: `standby` (listening only for the wake word).

WebSocket topics added in M3: `voice.wake {transcript}`, `voice.reply {text}`, `voice.models [...]`;
`voice.utterance` is now `{ trigger, captured_ms, transcribed, transcript, reply, stopped_by, task_id }`.

### Notifications — M2
| GET | `/v1/notifications` | `?unread_only=&limit=&offset=` | `{ items: Notification[], total, unread }` |
| POST | `/v1/notifications/{id}/read` | – | 204 · 404 |
| POST | `/v1/notifications/read-all` | – | `{ marked }` |

### System metrics — M2
| GET | `/v1/system/metrics` | – | `{ cpu_percent, cpu_count, memory_*, disk_*, service_rss_bytes, service_cpu_percent, uptime_s }` |

### AI providers — M4
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/v1/ai/status` | – | credential store (kind, secure, available), anthropic (configured, key_hint, settings, last_test), claude_code (settings, detected, last_test), routing, fallback, limits, prices_as_of, month summary |
| PUT / DELETE | `/v1/ai/anthropic/key` | `{ api_key }` | 204 · 422 `invalid_api_key` · 409 `credential_store_unavailable` — the key is never returned |
| PATCH | `/v1/ai/settings` | any of `anthropic{model, effort, timeout_s, max_retries, refusal_fallback}`, `claude_code{enabled, binary, model, timeout_s}`, `routing{reasoning, coding}`, `fallback{enabled}`, `limits{monthly_usd, per_task_usd, per_project_usd, alert_pct}` | settings |
| GET | `/v1/ai/anthropic/models` | `?refresh` | `[{ id, display_name, max_input_tokens, max_tokens, price_known }]` |
| POST | `/v1/ai/{anthropic|claude_code}/test` | – | `{ ok, at, model, latency_ms, reply, error, error_code }` |
| POST | `/v1/ai/claude-code/detect` | – | `{ installed, binary, version, logged_in, auth_method, api_provider, detail }` |
| POST | `/v1/ai/complete` | `{ prompt, provider?, system?, max_tokens?, task_id? }` | `{ text, provider, model_served, stop_reason, refusal_category, fallbacks, usage[], billing_kind, cost_usd, reported_cost_usd, latency_ms }` · 402 `ai_budget` · 409 `ai_not_configured` · 401/429/502/504 `ai_*` |
| GET | `/v1/ai/usage` | `?month=YYYY-MM` | `{ api, claude_code, by_model, by_day, monthly_limit_usd, limit_used_pct }` |
| GET | `/v1/ai/usage/records` | `?limit&offset` | `{ items, total }` |

WebSocket topics added in M4: `ai.status { changed }`, `ai.usage { provider, cost_usd | failed }`.

### Requirement discovery — M5
| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/v1/discovery/messages` | `{ text, session_id?, source: typed|ui }` | `{ reply, session }`. Without `session_id` a new conversation and task start; with it, the text answers that conversation (409 if it is closed) |
| GET | `/v1/discovery/sessions` | `?active=bool` | `[session]` (newest first, without turns) |
| GET | `/v1/discovery/sessions/{id}` | – | session: `{ id, task_id, status, category, category_name, category_source, command, question, answers[], spec, notes, blocked_reason, turns[], created_at, updated_at, approved_at }` |
| PUT | `/v1/discovery/sessions/{id}/answers/{slot}` | `{ value }` (option id, list of ids, text or boolean) | `{ reply, session }` · 400 for an unknown slot or a value outside its options |
| POST | `/v1/discovery/sessions/{id}/approve` | – | `{ reply, session }` · 409 when nothing is waiting for approval |
| POST | `/v1/discovery/sessions/{id}/cancel` | – | `{ reply, session }` |
| POST | `/v1/tasks/{id}/answers` | `{ text }` | `{ reply, session }` (contract drafted before M5) |
| GET | `/v1/tasks/{id}/spec` | – | `{ spec, status, session_id }` · 404 while requirements are still being gathered |
| POST | `/v1/tasks/{id}/spec/approve` | – | `{ reply, session }` |
| GET | `/v1/discovery/status` | – | `{ settings, using: claude|local, detail }` |
| PATCH | `/v1/discovery/settings` | any of `engine(auto|local)`, `approval(auto|always)`, `followup_listen` | settings |
| GET | `/v1/discovery/catalog` | – | `[{ id, name, description, questions }]` for the 19 categories |

`reply` is `{ session_id, task_id, text, status, expects_answer, options[], slot, listen }`.
Session `status`: `choosing_category`, `asking`, `resolving_conflict`, `awaiting_approval`,
`changing`, `ready`, `cancelled`, `blocked`. The specification (`spec`) holds `title, category,
summary, requirements[], assumptions[], open_questions[], scope{scale, components, rationale},
integrations[], hosting, dependencies[{capability, milestone, available}], engines, notes,
approval_required`.

WebSocket topics added in M5: `discovery.updated { session_id, task_id, status }`,
`discovery.settings`, `voice.followup { wait_s }`.

### Planned (contracts drafted, not implemented)
| Area | Routes | Milestone |
|---|---|---|
| Approvals | `GET /v1/approvals?status=pending`, `POST /v1/approvals/{id}/decide` (user re-auth for privileged) | M6 |
| Projects/Memory | `/v1/projects`, `/v1/projects/{id}/search` | M8 |
| GitHub | `/v1/github/accounts`, `/v1/github/repos`, `/v1/github/repos/{id}/pulls` | M9 |
| Servers | `/v1/servers`, `/v1/servers/{id}/hostkey/verify`, `/v1/servers/{id}/diagnostics` | M10 |
| Deployments | `/v1/deployments/plan`, `/v1/deployments/{id}`, `/v1/deployments/{id}/rollback` | M13 |

## 3. WebSocket `/v1/ws` — M1

Client → server: `{"type":"auth","token":"…"}` (first frame), then `{"type":"ping"}`.

Server → client envelope:

```json
{ "type": "event", "topic": "hello" | "pong" | "health.changed" | "task.created" | "task.updated"
           | "voice.state" | "voice.level" | "voice.settings" | "voice.utterance" | "voice.error"
           | "notification.created" | "notification.read" | "system.metrics",
  "ts": "2026-11-12T15:00:00Z", "data": { … } }
```

Close codes: `4401` auth failed/timeout, `4403` origin not allowed, `1001` server shutdown.

## 4. Tauri commands (Rust ↔ React) — M1

| Command | Returns |
|---|---|
| `backend_connection` | `{ baseUrl, wsUrl, token }` once the service is live; error string otherwise |
| `backend_status` | `{ state: "starting"|"running"|"restarting"|"failed"|"stopped", restarts, lastError, pid }` |
| `restart_backend` | `()` |
| `sync_tray(muted, voiceState)` | `()` — updates tray tooltip and mute checkbox (M2) |
| `ptt_shortcut` | `"Ctrl+Shift+Space"` (M2) |

The global push-to-talk hotkey is handled in Rust and calls `/v1/voice/ptt/start|stop`
directly, so it works while the window is hidden; failures are emitted as `voice://error`.

Rust also emits the Tauri event `backend://status` on every supervisor state change.
