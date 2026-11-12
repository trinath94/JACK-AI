# JACK AI

**GIVE THE COMMAND. JACK DELIVERS.**

JACK AI is a voice-first autonomous AI desktop assistant for Windows 10/11 (x64), built with
Tauri 2 (Rust + React/TypeScript) and a local Python/FastAPI service.

> **Status: 0.1.0 developer preview — Milestone 1 (foundation) of 18.**
> The desktop app, supervised local service, durable tasks and audit log work today.
> Voice, Claude integration, agents, GitHub, servers, deployment and the creative studio are
> **not implemented yet**. The app marks each of them with the milestone that delivers it.
> See [`docs/milestones/M1-REPORT.md`](docs/milestones/M1-REPORT.md) for the evidence-based status.

## Repository layout

```
apps/desktop            Tauri 2 desktop app (Rust core in src-tauri/, React UI in src/)
services/api            Local service: FastAPI, auth, health, tasks, audit, migrations
packages/shared-types   API types generated from the service OpenAPI schema
docs/                   Architecture, security, installation, user and developer guides
scripts/                Sidecar build, type generation, signing
tests/e2e               End-to-end smoke test of the release build
.github/workflows       CI: Linux tests and the Windows installer build
```

Directories that only contain a README are reserved for later milestones (`docs/ROADMAP.md`).

## Quick start (development)

```bash
pnpm install
(cd services/api && uv sync)
pnpm dev
```

See [`docs/developer-guide/README.md`](docs/developer-guide/README.md) for tests and tooling,
and [`docs/installation/INSTALL.md`](docs/installation/INSTALL.md) for the Windows installers.

## Design documents

[Architecture](docs/architecture/ARCHITECTURE.md) ·
[Components](docs/architecture/COMPONENTS.md) ·
[Database](docs/architecture/DATABASE.md) ·
[Threat model](docs/security/THREAT_MODEL.md) ·
[API contracts](docs/architecture/API_CONTRACTS.md) ·
[Roadmap](docs/ROADMAP.md) ·
[Acceptance tests](docs/architecture/ACCEPTANCE_TESTS.md) ·
[Dependencies & licensing](docs/architecture/DEPENDENCIES.md)

Development happens on `dev/*` branches and lands on `main` through pull requests.
