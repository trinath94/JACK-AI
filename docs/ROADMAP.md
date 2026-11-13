# JACK AI — Development Roadmap

Deliverable 6 of Section 30. Milestones follow Section 27 in order; a milestone starts only
when its dependencies are done. Each one finishes with tests, docs, a commit to a `dev/*`
branch, and a report in `docs/milestones/`.

| # | Milestone | Depends on | Exit criteria (evidence required) | Status |
|---|---|---|---|---|
| 1 | Foundation: Tauri 2, React, Rust, FastAPI | – | Authenticated loopback service supervised by Rust; health + WS live in UI; task/audit persistence; CI on Linux + Windows build job | **Done** ([report](milestones/M1-REPORT.md)) |
| 2 | Dashboard & voice interface | 1 | Section 21 dashboard; voice settings, mic selection, mute/privacy enforced server-side; push-to-talk (UI + global hotkey) with real capture and live level; notification centre; system metrics; tray mute; start with Windows; shortcuts | **Done** ([report](milestones/M2-REPORT.md)) |
| 3 | Wake word & speech | 2 | Wake word "Jack"/"Hey Jack" + FA/MD evaluation report; Silero VAD; Whisper (faster-whisper) ASR; Windows SAPI TTS; push-to-talk; privacy mode; conversation history | **Done** ([report](milestones/M3-REPORT.md)) — wake word ships as `keyword-asr`; a custom openWakeWord model remains open (D-3) |
| 4 | Claude provider abstraction | 1 | Anthropic API provider + Claude Code provider; Credential Manager storage; usage/cost tracking; spend limits; connection test | **Done** ([report](milestones/M4-REPORT.md)) — a successful call against the real API awaits your key |
| 5 | Requirement discovery | 4 | Category classifier for 19 categories; one-question-at-a-time loop; structured spec; approval for large projects | **Done** ([report](milestones/M5-REPORT.md)) — understanding of free-form answers with real Claude awaits your key |
| 6 | Durable task orchestration | 1,4 | Temporal sidecar; workflows survive kill -9 and reboot; pause/resume/cancel/retry; approvals; PostgreSQL embedded (D-1) | Not started |
| 7 | Multi-agent system | 6 | 17 agents with schemas, allow-lists, limits; policy engine; orchestrator review; file conflict detection | Not started |
| 8 | Project memory | 6 | Indexing, pgvector semantic search, verified-vs-assumption marking, export | Not started |
| 9 | GitHub | 4,7 | OAuth device flow + fine-grained PAT; multi-account; branch/PR workflow honouring protections; never force-push | Not started |
| 10 | Ubuntu SSH | 7 | Profiles; host-key verification; diagnostics; non-root deploy user | Not started |
| 11 | Autonomous development | 7,8,9 | Isolated worktrees; Claude Code sessions; Test B & C pass | Not started |
| 12 | QA & self-healing | 11 | Test runners, bounded repair loop, evidence store | Not started |
| 13 | Staging & production deploy | 10,12 | 25-step pipeline; release dirs; atomic switch; rollback; Test E passes | Not started |
| 14 | Creative studio | 4 | ≥1 real image provider adapter; asset library; quota tracking; Test F | Not started |
| 15 | Windows & browser automation | 7 | Restricted PowerShell; Playwright isolated profiles; approvals for purchases/submissions | Not started |
| 16 | Self-upgrade & updater | 11,12 | Separate updater; signature verification; rollback; Test G | Not started |
| 17 | Security hardening | all | Pen-test checklist; rate limiting; fuzzing of local API; Test I | Not started |
| 18 | Installer, release, docs | all | Signed (if cert configured) EXE + MSI; install/uninstall/upgrade guides; Tests A–J | Not started |

## Open decisions requiring approval

| ID | Decision | Proposed | Needed by |
|---|---|---|---|
| D-1 | PostgreSQL in a desktop install | **Approved 2026-11-13:** embedded PostgreSQL from M6; SQLite keeps local preferences | M6 (decided) |
| D-2 | Code-signing certificate | You provide an OV/EV certificate or Azure Trusted Signing account | M18 |
| D-3 | Dedicated wake-word model | M3 shipped `keyword-asr` (MIT-only, no decision needed). Optional upgrade: train a custom openWakeWord model with commercially licensed training data, if the field miss rate is too high | After field testing |
| D-4 | Image provider(s) for M14 | Choose at least one (e.g. OpenAI Images, Stability AI, Google Imagen) | M14 |
