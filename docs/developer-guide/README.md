# Developer Guide

## Prerequisites

| Tool | Version | Used for |
|---|---|---|
| Node.js | 22 LTS | Frontend tooling |
| pnpm | 10.28 (pinned via `packageManager`) | JS workspace |
| Rust | stable ≥ 1.85 | Tauri core |
| uv | ≥ 0.11 | Python env + lockfile |
| Python | 3.12+ | Local service |
| Windows | WebView2 runtime, MSVC build tools | Desktop build |
| Linux (dev/CI only) | `libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev libxdo-dev libssl-dev` | Tauri on Linux |

End users need none of these: the installer ships the frozen service and the WebView2 bootstrapper.

## First run

```bash
pnpm install
cd services/api && uv sync && cd ../..
pnpm dev            # = pnpm --filter @jack/desktop tauri dev
```

In debug builds the Rust supervisor starts the service from source with
`uv run jack-service` in `services/api`. To use a frozen binary instead:

```bash
pnpm build:sidecar
JACK_SERVICE_BIN="$PWD/apps/desktop/src-tauri/binaries/jack-service-<triple>" pnpm dev
```

## Running the service by itself

```bash
cd services/api
JACK_SESSION_TOKEN=$(python -c 'import secrets;print(secrets.token_hex(32))') JACK_PORT=8765 uv run jack-service
```

Configuration variables are listed in `docs/installation/CONFIGURATION.md`.

## Tests

| Suite | Command |
|---|---|
| Service (SQLite) | `cd services/api && uv run pytest` |
| Service (PostgreSQL) | `JACK_TEST_DATABASE_URL=postgresql+psycopg://user:pw@127.0.0.1:5432/db uv run pytest` |
| Service lint/types | `uv run ruff check src tests && uv run mypy src` |
| Frontend | `pnpm --filter @jack/desktop test` and `… typecheck` |
| Rust unit + integration | `pnpm build:sidecar`, then in `apps/desktop/src-tauri`: `JACK_SERVICE_BIN=$PWD/binaries/jack-service-<triple> cargo test` |
| Rust lint | `cargo fmt --check && cargo clippy --all-targets -- -D warnings` |

The integration test `tests/supervisor_it.rs` kills the real service and checks the supervisor
restarts it with a rotated token. It is skipped when `JACK_SERVICE_BIN` is not set.

## Changing the API

1. Edit the FastAPI routes / Pydantic schemas in `services/api/src/jack_api`.
2. `pnpm gen:types` regenerates `packages/shared-types/src/api.gen.ts`. CI fails if you forget.
3. Schema changes need an Alembic revision in `services/api/src/jack_api/migrations/versions`
   (`JACK_DATABASE_URL=sqlite:///tmp.db uv run alembic revision --autogenerate -m "…"`), then review it by hand.

## Adding a Tauri command

Add the function in `src-tauri/src/lib.rs`, register it in `generate_handler!`, add its name to
the allow-list in `src-tauri/build.rs`, and add `allow-<command-name>` to
`capabilities/default.json`. A command that is not in the allow-list cannot be called from the
WebView.

## Branching

Work on `dev/<milestone-or-topic>` branches and merge to `main` through pull requests. Never force-push shared branches.
