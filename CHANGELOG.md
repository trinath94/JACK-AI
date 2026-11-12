# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added — Milestone 3 (wake word and speech)
- Local speech pipeline: 80 Hz high-pass filter, streaming Silero VAD v6, utterance
  segmentation, Whisper speech recognition (faster-whisper, int8, `tiny.en` / `base.en` /
  `small.en`). Models download only when you ask, then work offline.
- Wake word **"Jack" / "Hey Jack"** (engine `keyword-asr`): standby listening, "Yes, I'm
  listening" then the command, or the command in one breath ("Jack, open GitHub"); two-tier
  sensitivity with a sound-alike veto; evaluation harness and report.
- Spoken commands, by push-to-talk or wake word, become voice tasks; JACK replies with what it
  did and says that execution comes later.
- Spoken replies: Windows SAPI voices (espeak-ng on Linux for development), voice and speed
  selection, test and stop, interrupted by push-to-talk; JACK ignores its own voice.
- Conversation history (migration 0003): text only, retention (30 days default), opt-out,
  clear; never in privacy mode.
- Voice page: speech models, recognition, wake word, spoken replies, history; dashboard shows
  the last exchange; tray shows "listening for Jack".
- CI: real-model speech tests (Silero + Whisper on synthesised speech), e2e with spoken
  commands and the wake word on the release build, Windows SAPI test.

### Fixed
- Push-to-talk clipped the last word when the key was released as speech ended (the queue is
  now drained and a 250 ms tail captured); found by a real-model test.
- espeak-ng reported success with no audio device; playback failures are now reported.
- The no-audio watchdog allows 4 s for slow audio drivers to start.

### Added — Milestone 2 (dashboard and voice interface)
- Voice engine: push-to-talk microphone capture through PortAudio with a live input level. Audio
  is reduced to a level and discarded immediately. Microphones are selected by a stable id; the
  microphone closes automatically after the maximum listening time; a no-audio watchdog reports
  microphones that open but deliver nothing; mute and privacy mode are enforced by the service;
  every capture is audited. Wake word, speech recognition and speech synthesis are reported as
  unavailable until Milestone 3.
- Global hold-to-talk hotkey **Ctrl+Shift+Space** that works while the window is hidden.
- Tray: mute-microphone toggle and a voice-state tooltip.
- Start with Windows; an autostart launch opens straight to the tray.
- Notification centre (migration 0002): task terminal and hold states, component health
  degradation and recovery, microphone problems; live updates; mark read / mark all read.
- System metrics (CPU, memory, disk, service memory), streamed to the dashboard.
- Section 21 dashboard: voice orb driven by the live level, microphone and wake-word status,
  current task and timeline, system resources, approval queue (empty until M6), recent events,
  integration status, service and component health.
- Voice Assistant page; shortcut help (`?`), Ctrl+K command focus, Ctrl+4 for Voice; the theme
  follows the OS live in system mode.
- CI: Linux end-to-end job on the release build (virtual display and virtual microphone);
  Windows smoke test of the frozen sidecar.

### Fixed
- Status pills no longer wrap next to long labels.

### Added — Milestone 1 (foundation)
- Section 30 design documents: architecture, components, database, threat model, API contracts,
  roadmap, acceptance test plan, dependencies and licensing.
- Local service (FastAPI) bound to loopback only, with a per-launch bearer token, Host-header
  DNS-rebinding defence, Tauri-only CORS/WebSocket origins and first-frame WebSocket auth.
- Health registry (api, database, disk) with live WebSocket updates.
- Durable tasks with a validated lifecycle state machine; pause, resume and cancel.
- Append-only, hash-chained audit log with verification; failed authentication is audited.
- Secret redaction for console and rotating file logs.
- Alembic migrations; schema runs on SQLite and PostgreSQL 16.
- Tauri 2 desktop shell: Rust supervisor (token rotation, restart with back-off, Windows Job
  Object, graceful Unix shutdown), system tray, close-to-tray, single instance, strict CSP,
  allow-listed commands.
- React UI: 16-section navigation, live service health, command entry, task timeline, audit view,
  theming, keyboard shortcuts.
- Shared TypeScript API types generated from OpenAPI with a CI drift check.
- CI: Linux test jobs and a Windows job that builds NSIS (`JACK-AI-Setup-x64.exe`) and MSI
  (`JACK-AI-x64.msi`) installers with checksum and signature reporting.
