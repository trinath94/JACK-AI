# JACK AI — System Architecture

Status: **Approved baseline for Milestone 1** · Version 0.1 · Owner: Principal Architect

This document is deliverable 1 of Section 30. It describes the target architecture for the
whole product and states explicitly which parts exist today. Companion documents:

| # | Document | Path |
|---|----------|------|
| 1 | Architecture (this file) | `docs/architecture/ARCHITECTURE.md` |
| 2 | Component diagram | `docs/architecture/COMPONENTS.md` |
| 3 | Database design | `docs/architecture/DATABASE.md` |
| 4 | Security threat model | `docs/security/THREAT_MODEL.md` |
| 5 | API contracts | `docs/architecture/API_CONTRACTS.md` |
| 6 | Development roadmap | `docs/ROADMAP.md` |
| 7 | Acceptance test plan | `docs/architecture/ACCEPTANCE_TESTS.md` |
| 8 | External dependencies & licensing | `docs/architecture/DEPENDENCIES.md` |

---

## 1. Goals and non-goals

**Goals.** A voice-first Windows desktop application that turns one natural-language command
into a durable, auditable task that is planned, executed by least-privilege agents, tested,
and — with explicit human approval where policy requires — deployed and verified.

**Non-goals.**
- A chatbot demo. Every capability is backed by a real integration or is reported as
  *not implemented* / *awaiting credentials*.
- Bypassing any provider's authentication, licensing, CAPTCHA, MFA, or rate limits.
- Using a Claude Pro/Max *subscription* as if it were Anthropic *API* credit. These are
  separate products. Subscription usage is only reachable through the officially supported
  Claude Code login flow, and is metered and displayed separately from API billing.

## 2. Architectural principles

1. **Durable state over conversation state.** Progress lives in the database and workflow
   engine, never only in an LLM context window. Any process may die at any time.
2. **Policy, not UI toggles.** Autonomy modes are enforced by the policy engine at the tool
   boundary. The UI only reflects them.
3. **The model is untrusted.** AI output, repository content, web pages and tool output are
   data. No model can approve its own privileged action; approvals come from the
   authenticated user and are bound to *action + target + scope + expiry*.
4. **Least privilege per agent.** Each agent has an allow-list of tools; each tool declares a
   risk class; the policy engine evaluates every call.
5. **Local first, nothing exposed.** All JACK services bind to `127.0.0.1` only and require a
   per-launch secret. Nothing listens on a public interface.
6. **Honest reporting.** "Success" requires evidence (test output, health-check response,
   signature verification). The UI distinguishes *verified* from *assumed*.

## 3. Runtime topology (Windows)

```
┌──────────────────────── JACK AI.exe (Tauri 2, Rust) ────────────────────────┐
│  WebView2 ── React UI (presentation only, no secrets persisted)             │
│     │  Tauri IPC (in-process, capability-scoped commands)                   │
│  Rust core: tray · single-instance · supervisor · credential bridge ·       │
│             native audio (M3) · restricted PowerShell runner (M15)          │
└──────┬───────────────────────────────────────────────────────────────────────┘
       │ spawns + supervises (sidecars, child processes, same user)
       ▼
┌─ jack-service.exe (Python 3.12+, FastAPI, frozen) ─ 127.0.0.1:<ephemeral> ──┐
│  api            REST + authenticated WebSocket, health registry, audit       │
│  orchestrator   LangGraph graphs (M6–M7), runs inside Temporal activities     │
│  agents         17 agent definitions, schemas, tool allow-lists (M7)          │
│  tool-executor  policy engine + tool adapters (git, ssh, docker, pwsh…)       │
│  project-memory indexing, semantic search (pgvector) (M8)                     │
│  voice          wake word (openWakeWord), VAD, ASR (Whisper), TTS (M3)        │
│  integrations   GitHub, Anthropic, Claude Code, image providers…              │
└──────┬───────────────────────────────┬─────────────────────────────────────┘
       │                               │
       ▼                               ▼
  SQLite (local prefs,          Temporal dev server (sidecar, M6)
  device state)                 PostgreSQL + pgvector (embedded, M6/M8)

  jack-updater.exe — separate process; replaces binaries only when the app is stopped (M16)
```

### 3.1 Why a Python sidecar

The AI stack the spec mandates (LangGraph, Temporal Python SDK, openWakeWord, Whisper,
Anthropic SDK, Playwright) is Python-native. Rust owns everything that must be native or
security-critical on the host (process supervision, tray, Windows Credential Manager, audio
capture, signature verification). The Python service is frozen with PyInstaller into a single
executable so end users never install Python (Section 23).

### 3.2 Local communication & authentication (implemented in M1)

1. On every launch, the Rust supervisor generates a 256-bit random session token from the OS
   CSPRNG and selects a free loopback port.
2. It starts `jack-service` with `JACK_SESSION_TOKEN` and `JACK_PORT` in the **child's
   environment only** (never on the command line, which is visible to other processes).
3. The service binds `127.0.0.1` only and rejects requests unless
   - `Authorization: Bearer <token>` matches (constant-time compare), **and**
   - the `Host` header is `127.0.0.1:<port>` or `localhost:<port>` (DNS-rebinding defence), **and**
   - for WebSocket upgrades, the `Origin` is the Tauri origin (or absent for native clients).
4. The React UI obtains `{baseUrl, token}` through a Tauri command; the token is held in
   memory only.
5. WebSocket: browsers cannot set headers on WebSocket upgrades, so the client sends
   `{"type":"auth","token":…}` as the first frame; the server closes with code 4401 if it does
   not arrive within 5 s or does not match.
6. Every rejected authentication attempt produces an `audit_events` row.

`GET /health/live` is the single unauthenticated route and returns only `{"status":"ok"}`
so the supervisor can probe liveness before it hands out the token.

### 3.3 Health monitoring & recovery

- Each internal component registers a health probe with the **health registry** (`api`,
  `database`, and later `temporal`, `postgres`, `voice`, `providers`). `GET /v1/health`
  aggregates them; changes are pushed over WebSocket as `health.changed` events.
- The Rust supervisor polls `/health/live`; on crash or three failed probes it restarts the
  service with exponential back-off (1 s → 30 s, max 5 consecutive attempts, then surfaces a
  persistent error in the UI and tray).
- Recovery matrix (target behaviour; milestone in brackets):

| Failure | Behaviour |
|---|---|
| App crash / Windows restart | Supervisor restarts on launch; Temporal replays workflows from history; tasks in non-idempotent steps are marked `needs_review` instead of auto-resumed [M6] |
| Service crash | Supervisor restart with back-off [**M1**] |
| Network loss | Provider calls fail with typed errors → Temporal retry policy; UI shows offline [M4/M6] |
| Claude API failure | Retry w/ jitter (configurable), then explicit configured fallback only — never silent provider switch [M4] |
| SSH server disconnect | Step fails closed; remote state re-inspected before retry [M10] |
| Interrupted dev task | Work happens on a git branch in an isolated worktree; resume re-reads `git status` [M11] |
| Failed deployment | Atomic symlink switch → automatic rollback to previous release + report [M13] |

## 4. Monorepo layout

Follows Section 26 with one justified addition: `services/api` is the Python package that hosts
the FastAPI app and wires the other service packages together (they are libraries loaded into
one process to keep the Windows footprint to a single frozen executable; each is still an
independent package with its own tests and may be split into its own process later).

```
apps/desktop          Tauri 2 + React + TS + Tailwind + Framer Motion + Lucide   [M1]
apps/web-admin        reserved
services/api          FastAPI app, auth, health, WS hub, DB, audit, tasks         [M1]
services/orchestrator LangGraph + Temporal workflows                              [M6]
services/voice        wake word, VAD, ASR, TTS                                    [M3]
services/agents       agent registry & definitions                                [M7]
services/tool-executor policy engine & tool adapters                              [M7+]
services/project-memory knowledge engine                                          [M8]
services/integrations  GitHub, SSH, Anthropic, Claude Code, image providers       [M4,M9,M10,M14]
services/updater       update client + standalone updater                         [M16]
packages/shared-types  API/WS contract types shared by UI (generated from OpenAPI) [M1]
packages/*             ui, security, provider-sdk reserved
migrations             top-level pointer; Alembic lives in services/api/migrations
scripts installer docker .github/workflows
```

## 5. Data storage

| Store | Holds | Notes |
|---|---|---|
| SQLite (`%LOCALAPPDATA%\ai.jack.desktop\data\jack.db`) | preferences, device, tasks & audit in single-user mode until PostgreSQL lands | WAL mode, Alembic migrations [**M1**] |
| PostgreSQL 16 + pgvector | task history, projects, audit, memory embeddings | Embedded portable PostgreSQL started as a sidecar on loopback with a random password in Credential Manager. Schema is DB-agnostic (SQLAlchemy 2), CI already runs the suite against PostgreSQL [M6/M8] |
| Windows Credential Manager | API keys, PATs, OAuth refresh tokens, SSH key passphrases | Only references (`credential_ref`) are stored in databases [M4] |
| Temporal (SQLite file) | workflow event history | `temporal server start-dev --db-filename` sidecar, loopback only [M6] |
| Redis | not used | Not justified for a single-user desktop; revisit only for a shared multi-user deployment |

> **Open decision for approval (D-1).** Section 2 fixes PostgreSQL for task history. Shipping
> PostgreSQL inside a desktop installer adds ~60 MB and a second supervised server. Proposal:
> keep PostgreSQL as specified, embedded, introduced at M6; SQLite carries M1–M5. No change is
> made to the approved stack without your sign-off.

## 6. AI provider layer (M4)

`provider-sdk` defines `LLMProvider` (`complete`, `stream`, `tool_call`, `count_tokens`,
`health`) and `CodingAgentProvider` (`run_session` in a workspace). Implementations:

- `AnthropicApiProvider` — Anthropic Messages API, key from Credential Manager.
- `ClaudeCodeProvider` — drives the officially installed Claude Code CLI / Agent SDK, which
  authenticates via its own supported login (API key *or* the user's own subscription login).
  JACK never reads, copies or extracts those credentials.

Routing: reasoning/orchestration → API provider; repository coding sessions → Claude Code
where configured. Fallbacks only if the user has configured them, and a fallback that changes
cost or data-handling requires a confirmation recorded in `approvals`.

## 7. Task model (summary)

Every request creates a `tasks` row with a lifecycle state machine
(`RECEIVED → UNDERSTANDING → REQUIREMENTS → PLANNING → APPROVAL → EXECUTION → TESTING → REPAIR
→ RELEASE_PREPARATION → DEPLOYMENT_APPROVAL → DEPLOYMENT → VERIFICATION → COMPLETED`, plus
`WAITING_FOR_INFORMATION, WAITING_FOR_APPROVAL, PAUSED, CANCELLED, FAILED, ROLLED_BACK`).
Transitions are validated server-side; every transition is an audit event. M1 implements the
table, the state machine and the transition validator; execution arrives in M6.

## 8. Security architecture (summary)

See `docs/security/THREAT_MODEL.md`. Key controls: loopback-only + per-launch token +
Host/Origin checks (M1); secret redaction in logs (M1); policy engine at the tool boundary
with risk classes `read`, `write_workspace`, `execute_sandboxed`, `network`, `privileged`,
`destructive`, `production`, `financial` (M7); approvals bound to action/target/scope/expiry
with user re-authentication for `production`/`destructive` (M7); signed updates verified
before install (M16).

## 9. Packaging (summary)

Tauri bundler on a Windows runner produces NSIS (`JACK-AI-Setup-x64.exe`) and WiX
(`JACK-AI-x64.msi`). The frozen `jack-service.exe` is shipped as a Tauri sidecar
(`externalBin`). Code signing is wired through `signCommand` and is only enabled when a
certificate is configured; the release report states the signature verification result
(`Get-AuthenticodeSignature`) and never claims signed otherwise.

## 10. What exists after Milestone 1

See `docs/milestones/M1-REPORT.md` for the evidence-based status.
