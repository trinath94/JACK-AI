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
| `JACK_METRICS_INTERVAL_S` | `3` | System metrics push period (only while the UI is connected) |
| `JACK_SUPERVISOR_PID` | set by the app | The service exits if this process disappears (POSIX) |
| `JACK_MODELS_DIR` | sibling `models` folder | Where speech models are downloaded and loaded from |

## In-app settings

| Where | Setting | Stored in |
|---|---|---|
| Settings → Appearance | Theme, accent colour, compact sidebar | WebView local storage (per user) |
| Settings → Startup | Start with Windows. Adds a per-user `Run` registry entry with `--autostart`, so JACK starts hidden in the tray | Windows registry (HKCU) |
| Voice Assistant | Microphone, mute, privacy mode, maximum push-to-talk time (5–120 s), wake word on/off and sensitivity, command model (`tiny.en` / `base.en` / `small.en`), end-of-speech pause, spoken replies on/off, voice, speed, keep history, retention days | Service database, `settings` table, key `voice` |
| Voice Assistant → Speech models | Downloaded Whisper models | `%LOCALAPPDATA%\ai.jack.desktop\models\` (override: `JACK_MODELS_DIR`) |
| Tray | Mute microphone | Same as above |

The push-to-talk hotkey is fixed to **Ctrl+Shift+Space** in this version.

Microphones are stored by host API and name (for example `Windows WASAPI:Headset Microphone`),
not by index, so the selection survives reboots. If the selected microphone is unplugged, push-to-talk
reports it instead of silently using another device. Choose **System default** to follow Windows.

AI provider, GitHub and server settings will be added in later milestones (see `docs/ROADMAP.md`).
