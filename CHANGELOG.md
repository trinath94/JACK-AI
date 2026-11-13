# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added — Milestone 5 (requirement discovery)
- Requirement discovery for the 19 task categories of Section 6: JACK identifies the kind of job,
  then asks only the essential questions, one at a time, with options and a sensible default.
- Understanding with Claude (schema-constrained JSON, validated against the catalogue) when a
  provider is set up, or with local rules; Claude failures fall back to local rules for that turn.
- Answers remembered and never asked twice; facts in the opening request are picked up;
  "you decide", "use defaults", "cancel"; changes at review time; conflict detection.
- Structured specification: requirements, assumptions, scope and size, integrations, hosting,
  dependencies on JACK capabilities, open questions and notes.
- Medium and large jobs wait for approval; small jobs go straight to planning. Task timeline:
  UNDERSTANDING → REQUIREMENTS ⇄ WAITING_FOR_INFORMATION → (WAITING_FOR_APPROVAL) → PLANNING.
- Security audits stop unless you confirm you own, or are allowed to test, the targets.
- Voice: spoken commands go through discovery; after a question JACK listens for the answer for a
  few seconds without the wake word (never when muted or in privacy mode).
- **Command Centre** (Ctrl+6) with the conversation, an editable specification and approval; the
  Home command box carries on the conversation.
- Migration 0005: `requirement_sessions`, `requirement_turns`. Structured-output support in both
  providers.

### Added — Milestone 4 (Claude provider abstraction)
- AI provider layer with two providers behind one interface: the **Anthropic API** (official SDK
  2.8.0, your own key) and **Claude Code** (your installed CLI with its own sign-in).
- API key stored in **Windows Credential Manager**; never shown again, logged or written to the
  database; JACK refuses to store keys without a secure store.
- Model discovery, effort, timeout and retry settings, connection tests, provider health.
- Server-side refusal fallback (another Claude model) on by default where supported; the
  serving model and its price are recorded.
- Usage tracking per model (migration 0004): tokens, estimated cost from a dated price table
  (unknown models are not guessed), failures; Claude Code usage reported separately and never
  counted as API spend.
- Monthly, per-task and per-project spending limits checked before every request, with alerts.
- Provider fallback only when you turn it on; every switch is audited and announced.
- **Usage and Billing** page and test console; the dashboard shows Claude status and API spend.
- CI: Windows Credential Manager round trip; e2e configures a key through the UI against a
  local fake Messages API.

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
