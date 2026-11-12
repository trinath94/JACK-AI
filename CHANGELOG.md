# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning: [SemVer](https://semver.org/).

## [Unreleased]

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
