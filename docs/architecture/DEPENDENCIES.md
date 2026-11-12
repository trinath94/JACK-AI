# JACK AI — External Dependencies & Licensing

Deliverable 8 of Section 30. Versions are pinned in lockfiles (`pnpm-lock.yaml`,
`uv.lock`, `Cargo.lock`). Licences were checked against the projects' published licence
files at the time of writing; re-verify before each release (`scripts/licence-report` — M18).

## 1. Bundled software (ships inside the installer)

| Component | Version (pinned) | Licence | Notes |
|---|---|---|---|
| Tauri + plugins | 2.12.x | MIT / Apache-2.0 | Desktop shell |
| Microsoft Edge WebView2 Runtime | Evergreen | Microsoft proprietary (redistributable) | Bootstrapper embedded by NSIS/MSI if missing |
| React / React DOM | 19.x | MIT | |
| Tailwind CSS | 4.x | MIT | |
| Framer Motion | 12+/14.x | MIT | |
| Lucide icons | 1.x | ISC | |
| Python runtime (frozen via PyInstaller) | 3.12+ | PSF | PyInstaller bootloader is GPL-2.0 **with a bundling exception** permitting distribution of frozen apps under any licence |
| FastAPI, Starlette, Pydantic, Uvicorn | see `uv.lock` | MIT / BSD-3 | |
| SQLAlchemy, Alembic | 2.1.x / 1.x | MIT | |
| LangGraph | 1.x | MIT | M6 |
| Temporal Python SDK | 1.x | MIT | M6 |
| Temporal CLI (dev server) | 1.x | MIT | Sidecar, M6 |
| PostgreSQL (embedded) | 16.x | PostgreSQL Licence | M6, pending D-1 |
| pgvector | 0.8.x | PostgreSQL Licence | M8 |
| openWakeWord | 0.6.x | Apache-2.0 (code). **Pre-trained models: CC BY-NC-SA 4.0 — not usable commercially**, and none exists for "Jack" | **Not shipped.** M3 ships the `keyword-asr` wake-word engine instead; openWakeWord needs a custom-trained model (D-3) |
| faster-whisper / CTranslate2 | 1.2.1 / 4.9.0 | MIT / MIT | **M3** speech recognition |
| Whisper models `tiny.en`, `base.en`, `small.en` (CTranslate2 conversions, `Systran/faster-whisper-*`) | – | MIT | **Downloaded on user request**, not bundled (75–484 MB each) |
| Silero VAD v6 (ONNX, bundled inside faster-whisper) | 6 | MIT | **M3** voice activity detection |
| onnxruntime | 1.31.1 | MIT | M3, runs Silero VAD |
| PyAV | 18.1.0 (pinned: faster-whisper 1.2.1 is incompatible with 19) | BSD-3; bundled FFmpeg libraries are **LGPL-2.1**, dynamically linked | M3, faster-whisper dependency |
| tokenizers, huggingface_hub | 0.23 / 2.4 | Apache-2.0 | M3 |
| numpy | 2.5.4 | BSD-3 | M3 |
| comtypes | 1.5.0 | MIT | M3, Windows SAPI text-to-speech (Windows only) |
| Windows SAPI 5 voices | OS component | Microsoft (part of Windows) | M3 spoken replies; not redistributed |
| espeak-ng | system package | GPL-3.0 | **Development and CI only** (Linux text-to-speech and synthetic test speech); called as a separate program, never bundled |
| Playwright (Python) + Chromium | 1.x | Apache-2.0; Chromium BSD | M15. Browsers downloaded on first use, not bundled, to keep installer size down |
| Anthropic Python SDK | 2.x | MIT | M4 |
| paramiko / asyncssh | – | LGPL-2.1 / EPL-2.0 | M10 — prefer **asyncssh (EPL-2.0 / GPL-2.0+)**, dynamic use only; final choice recorded in M10 |
| keyring (Rust) | 4.x | MIT / Apache-2.0 | Windows Credential Manager (M4) |
| python-sounddevice | 0.5.6 | MIT | M2 microphone capture. Bundles **PortAudio** (MIT) on Windows/macOS |
| psutil | 7.2.2 | BSD-3-Clause | M2 system metrics |
| tauri-plugin-global-shortcut / -autostart | 2.4.1 / 2.7.0 | MIT / Apache-2.0 | M2 push-to-talk hotkey, start with Windows |

## 2. External services (user-supplied accounts)

| Service | Required for | Billing / terms | JACK behaviour without it |
|---|---|---|---|
| Anthropic API | Reasoning, orchestration | Pay-as-you-go API, separate from Claude Pro/Max | Status `awaiting credentials` |
| Claude Code | Coding sessions | Authenticates with user's own API key or supported subscription login, per Anthropic terms | Coding falls back only to API provider if user configured it |
| GitHub | Repos, PRs | GitHub ToS; OAuth app or fine-grained PAT | GitHub page shows "Connect account" |
| Image provider(s) | Creative studio | Provider pricing | Creative studio shows provider setup |
| Premium TTS (optional) | Voices | Provider pricing | Windows SAPI voices used |
| Code-signing certificate | Signed installers | CA / Azure Trusted Signing | Unsigned build, reported as unsigned |

## 3. Development-only tooling

Node 22, pnpm 10, Rust 1.97 (stable), uv, Python 3.12/3.13, WiX Toolset v3 and NSIS (fetched by
the Tauri bundler on Windows runners), ruff, mypy, pytest, vitest, pip-audit, cargo-audit.
