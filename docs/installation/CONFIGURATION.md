# Configuration Guide

## Installed locations (Windows)

| What | Where |
|---|---|
| Application | `C:\Program Files\JACK AI\` (`JACK AI.exe`, `jack-service.exe`) |
| Database | `%LOCALAPPDATA%\ai.jack.desktop\data\jack.db` |
| Service logs | `%LOCALAPPDATA%\ai.jack.desktop\logs\jack-service.log` (rotated, 5 × 5 MB) |
| Desktop logs | `%LOCALAPPDATA%\ai.jack.desktop\logs\` (Tauri log plugin) |
| Credentials | Windows Credential Manager (from Milestone 4) |

## Service environment variables

The desktop app sets these for you. They only matter when running the service by hand.

| Variable | Default | Notes |
|---|---|---|
| `JACK_SESSION_TOKEN` | — (required) | ≥ 32 chars. The desktop app generates a fresh 256-bit token every launch |
| `JACK_PORT` | `8765` | The desktop app picks a free port |
| `JACK_HOST` | `127.0.0.1` | Must be a loopback address; anything else is refused |
| `JACK_DATA_DIR` | platform app-data dir | Database location; logs go to the sibling `logs` folder |
| `JACK_DATABASE_URL` | SQLite in the data dir | e.g. `postgresql+psycopg://…` (install the `postgres` extra) |
| `JACK_DEV_MODE` | `0` | `1` also allows the Vite dev origin `http://localhost:1420` |
| `JACK_EXIT_WITH_PARENT` | `0` | `1` exits the service if its parent process dies (POSIX) |
| `JACK_LOG_LEVEL` | `INFO` | |
| `JACK_WS_AUTH_TIMEOUT_S` | `5` | Seconds a WebSocket has to send its auth frame |
| `JACK_HEALTH_INTERVAL_S` | `10` | Background health check period |

## In-app settings

Settings → Appearance: theme (system, dark or light), accent colour, compact sidebar. These are
stored per user in the WebView's local storage.

AI provider, voice, GitHub and server settings will be added in later milestones (see `docs/ROADMAP.md`).
