# JACK AI — Database Design

Deliverable 3 of Section 30.

## 1. Conventions

- SQLAlchemy 2.x declarative models, **portable across SQLite and PostgreSQL**; Alembic owns
  every schema change (`services/api/migrations`). No `create_all` in production paths.
- Primary keys: UUIDv4 stored as `CHAR(36)` (portable); PostgreSQL may switch to native `uuid`
  in a later migration.
- Timestamps: UTC, `created_at`/`updated_at` on every mutable table.
- **No secrets in any table.** Secret-bearing entities hold `credential_ref` — an opaque key
  into Windows Credential Manager (`jack-ai/<kind>/<uuid>`).
- JSON payloads use the portable `JSON` type (`JSONB` on PostgreSQL).
- Audit integrity: `audit_events` is append-only (no UPDATE/DELETE from application code) and
  each row stores `prev_hash` + `hash = SHA-256(prev_hash ‖ canonical_json(row))`, giving a
  tamper-evident chain that `GET /v1/audit/verify` checks.

## 2. Entity overview

Legend: **M1** = implemented in Milestone 1; others are designed now and created by the
migration of the milestone noted.

| Entity | Key columns | Milestone |
|---|---|---|
| `devices` | id, name, os_version, app_version, first_seen_at, last_seen_at | **M1** |
| `audit_events` | id, seq, occurred_at, actor_type(user/agent/system), actor_id, action, target, outcome(allowed/denied/error), details JSON, prev_hash, hash | **M1** |
| `tasks` | id, title, command_text, source(voice/text), status, status_reason, mode, project_id?, parent_task_id?, created_at, updated_at, completed_at | **M1** |
| `task_events` | id, task_id, seq, from_status, to_status, reason, actor, occurred_at | **M1** |
| `settings` | key, value JSON, updated_at | **M1** |
| `users` | id, display_name, role(owner/operator/viewer), created_at | M6 |
| `ai_providers` | id, kind(anthropic_api/claude_code/openai_image/…), name, base_url, credential_ref, enabled, fallback_order | M4 |
| `ai_models` | id, provider_id, model_id, input_price_per_mtok, output_price_per_mtok, context_window | M4 |
| `usage_records` | id, provider_id, model_id, task_id?, project_id?, billing_kind(api/subscription), input_tokens, output_tokens, cost_usd, succeeded, occurred_at | M4 |
| `spend_limits` | id, scope(global/project/task), scope_id?, period, limit_usd, alert_pct | M4 |
| `conversations` | id, task_id?, project_id?, summary, created_at | M5 |
| `conversation_turns` | id, conversation_id, role, content, created_at | M5 |
| `requirement_specs` | id, task_id, category, spec JSON, status(draft/approved), approved_by?, approved_at? | M5 |
| `workflow_runs` | id, task_id, temporal_workflow_id, run_id, status, started_at, ended_at | M6 |
| `task_steps` | id, task_id, workflow_run_id, name, agent_id?, status, idempotent bool, attempt, input JSON, output JSON, started_at, ended_at | M6 |
| `approvals` | id, task_id, action, target, scope JSON, risk_class, requested_by, status(pending/approved/denied/expired), decided_by_user_id?, decided_at?, expires_at, nonce | M6 |
| `notifications` | id, level, kind, title, body, task_id?, created_at, read_at? | **M2** (migration 0002) |
| `agents` | id, key, name, version, allowed_tools JSON, limits JSON | M7 |
| `agent_executions` | id, agent_id, task_step_id, input JSON, output JSON, verdict(accepted/rejected), tokens, cost_usd | M7 |
| `tool_executions` | id, agent_execution_id?, tool, risk_class, args_redacted JSON, policy_decision, approval_id?, exit_code, started_at, ended_at | M7 |
| `projects` | id, name, description, workspace_path, repository_id?, default_branch, tech_stack JSON | M8 |
| `project_documents` | id, project_id, path, kind, content_hash, indexed_at | M8 |
| `memory_records` | id, project_id, kind(fact/decision/error/summary), content, provenance(verified/assumption), source_ref, embedding vector(1024) [pg only], superseded_by? | M8 |
| `github_accounts` | id, login, kind(oauth/pat), credential_ref, scopes JSON | M9 |
| `repositories` | id, github_account_id, full_name, default_branch, local_path?, protected bool | M9 |
| `servers` | id, name, host, port, username, auth_method(key/password), credential_ref, host_key_fingerprint, os, environment_id, project_id? | M10 |
| `server_environments` | id, name(local/dev/staging/prod), requires_approval bool | M10 |
| `test_reports` | id, task_id, project_id, suite, passed, failed, skipped, duration_s, artifact_path, created_at | M12 |
| `deployment_records` | id, project_id, server_id, release_id, environment, status, plan JSON, approval_id?, started_at, verified_at?, report JSON | M13 |
| `release_records` | id, project_id, version, git_sha, artifact_path, artifact_sha256, created_at | M13 |
| `backups` | id, server_id, kind(config/db), location, sha256, size_bytes, created_at, expires_at | M13 |
| `creative_assets` | id, project_id?, provider_id, prompt, params JSON, file_path, sha256, cost_usd | M14 |
| `voice_sessions` | id, started_at, ended_at, wake_word, asr_engine, transcript (retention-limited), task_id? | M3 |

## 3. Task state machine (enforced in code, M1)

```
RECEIVED → UNDERSTANDING → REQUIREMENTS → PLANNING → APPROVAL → EXECUTION → TESTING
TESTING → REPAIR → TESTING          (bounded by repair retry limit)
TESTING → RELEASE_PREPARATION → DEPLOYMENT_APPROVAL → DEPLOYMENT → VERIFICATION → COMPLETED
Small tasks may skip: PLANNING → EXECUTION, EXECUTION → COMPLETED, TESTING → COMPLETED
Any active state → WAITING_FOR_INFORMATION | WAITING_FOR_APPROVAL | PAUSED → (back to the state it left)
Any non-terminal state → CANCELLED | FAILED
DEPLOYMENT | VERIFICATION → ROLLED_BACK
Terminal: COMPLETED, CANCELLED, FAILED, ROLLED_BACK (retry creates a new attempt via FAILED → RECEIVED)
```

## 4. Retention

| Data | Default retention | Configurable |
|---|---|---|
| audit_events | 2 years; never auto-deleted while chain verification is enabled — archived instead | yes |
| voice transcripts | 30 days; raw audio is never stored | yes; privacy mode = 0 |
| conversation_turns | 180 days (summaries kept) | yes |
| usage_records | 2 years | yes |
| test/deployment artifacts | last 20 per project | yes |

## 5. Indexes (initial)

`tasks(status, updated_at)`, `task_events(task_id, seq)` unique, `audit_events(seq)` unique,
`audit_events(occurred_at)`, `usage_records(occurred_at, provider_id)`.
