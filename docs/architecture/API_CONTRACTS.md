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

### Planned (contracts drafted, not implemented)
| Area | Routes | Milestone |
|---|---|---|
| Voice | `GET/PUT /v1/voice/settings`, `POST /v1/voice/ptt/start|stop`, `GET /v1/voice/devices` | M3 |
| Providers | `GET/POST /v1/providers`, `POST /v1/providers/{id}/test`, `GET /v1/usage` | M4 |
| Requirements | `POST /v1/tasks/{id}/answers`, `GET /v1/tasks/{id}/spec`, `POST /v1/tasks/{id}/spec/approve` | M5 |
| Approvals | `GET /v1/approvals?status=pending`, `POST /v1/approvals/{id}/decide` (user re-auth for privileged) | M6 |
| Projects/Memory | `/v1/projects`, `/v1/projects/{id}/search` | M8 |
| GitHub | `/v1/github/accounts`, `/v1/github/repos`, `/v1/github/repos/{id}/pulls` | M9 |
| Servers | `/v1/servers`, `/v1/servers/{id}/hostkey/verify`, `/v1/servers/{id}/diagnostics` | M10 |
| Deployments | `/v1/deployments/plan`, `/v1/deployments/{id}`, `/v1/deployments/{id}/rollback` | M13 |

## 3. WebSocket `/v1/ws` — M1

Client → server: `{"type":"auth","token":"…"}` (first frame), then `{"type":"ping"}`.

Server → client envelope:

```json
{ "type": "event", "topic": "health.changed" | "task.created" | "task.updated" | "hello",
  "ts": "2026-11-12T15:00:00Z", "data": { … } }
```

Close codes: `4401` auth failed/timeout, `4403` origin not allowed, `1001` server shutdown.

## 4. Tauri commands (Rust ↔ React) — M1

| Command | Returns |
|---|---|
| `backend_connection` | `{ baseUrl, wsUrl, token }` once the service is live; error string otherwise |
| `backend_status` | `{ state: "starting"|"running"|"restarting"|"failed"|"stopped", restarts, lastError, pid }` |
| `restart_backend` | `()` |

Rust also emits the Tauri event `backend://status` on every supervisor state change.
