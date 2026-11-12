# JACK AI — Security Threat Model

Deliverable 4 of Section 30. Method: STRIDE per trust boundary, plus AI-specific threats.
Status column: **M1** = control implemented and tested in Milestone 1; `Mx` = planned.

## 1. Assets

A1 API keys, GitHub tokens, OAuth refresh tokens · A2 SSH private keys / passphrases ·
A3 user source code and project data · A4 production servers and databases ·
A5 integrity of the audit log · A6 the JACK installation itself (update channel) ·
A7 microphone audio and transcripts · A8 money (API spend, purchases).

## 2. Trust boundaries

| # | Boundary | Untrusted side |
|---|---|---|
| B1 | Other local processes / websites ↔ JACK loopback service | Any process or web page on the machine |
| B2 | Model output ↔ tool execution | LLM responses (can be steered by injected content) |
| B3 | External content ↔ agent context | Repos, web pages, docs, issues, server logs, tool output |
| B4 | JACK ↔ remote servers (SSH) | Network, the server itself |
| B5 | Update server ↔ installer/updater | Network, CDN, release storage |
| B6 | Microphone ↔ voice pipeline | Ambient audio, other people, media playback |

## 3. Threats and controls

| ID | Threat (STRIDE) | Boundary | Control | Status |
|---|---|---|---|---|
| T1 | Malicious web page calls `http://127.0.0.1:<port>` (CSRF) | B1 | Bearer token required on all `/v1/*`; token never in cookies, so the browser cannot attach it automatically | **M1** |
| T2 | DNS rebinding to the loopback port | B1 | `Host` header must be `127.0.0.1:<port>` / `localhost:<port>` | **M1** |
| T3 | Cross-origin WebSocket hijack | B1 | Origin allow-list (Tauri origins) + first-frame token auth with 5 s deadline | **M1** |
| T4 | Local process reads token from command line | B1 | Token passed via child env only; regenerated each launch | **M1** |
| T5 | Service exposed on LAN | B1 | Bind `127.0.0.1` only; startup refuses any other host | **M1** |
| T6 | Token / secret leaks into logs | all | Redaction filter on all log records (Bearer tokens, `sk-ant-…`, `ghp_…`, `github_pat_…`, PEM blocks, `password=`) | **M1** |
| T7 | Brute-forcing the token | B1 | 256-bit token, constant-time compare, failures audited | **M1** |
| T8 | Audit log tampering | A5 | Append-only, hash-chained rows; verification endpoint | **M1** |
| T9 | Prompt injection from repo/web content causes privileged action | B2/B3 | Policy engine evaluates every tool call independent of model; external content wrapped and labelled as data; privileged risk classes require user approval bound to action+target+scope+expiry; model cannot call the approval API | M7 |
| T10 | Agent exceeds its role (e.g. QA agent runs `ssh`) | B2 | Per-agent tool allow-lists checked by the policy engine, not the prompt | M7 |
| T11 | Approval replay / blanket approval | B2 | Approval nonce, single use, expiry, exact target match | M7 |
| T12 | Arbitrary shell via PowerShell tool | B2 | Constrained runner: allow-listed cmdlets, ConstrainedLanguage mode, working-dir jail, no `Invoke-Expression`; destructive verbs require approval | M15 |
| T13 | MITM on first SSH connection | B4 | Never auto-accept unknown host keys; fingerprint shown to user for verification and pinned | M10 |
| T14 | Over-privileged deployment | B4 | Dedicated non-root deploy user; narrowly scoped sudoers entries generated and shown for review | M10/M13 |
| T15 | Malicious update | B5 | Tauri updater minisign signature + Authenticode check before install; updater runs as separate process | M16 |
| T16 | Secrets stored in DB / memory | A1 | `credential_ref` only; Windows Credential Manager (DPAPI-backed) | M4 |
| T17 | Credential exfiltration by agent via network tool | B2 | Agents never receive raw secrets; integrations inject credentials inside the adapter | M4/M9 |
| T18 | Accidental activation / eavesdropping | B6 | **M2:** microphone opens only while push-to-talk is held (auto-close after max duration); samples reduced to a level in the audio callback and discarded; mute/privacy enforced by the service, not the UI; every capture start/stop audited; listening state shown in header, orb and tray. **M3 (done):** wake word, VAD and speech recognition run entirely on the device; no audio is ever sent anywhere or written to disk; only transcript text is kept, and not at all in privacy mode or with history off; standby start, wake detections, model downloads and history clearing are audited; while JACK speaks, captured audio is discarded (half-duplex), so JACK cannot wake itself | **M2 / M3** |
| T19 | Runaway spend | A8 | Global/project/task spend limits enforced before each call; no automatic purchases | M4 |
| T20 | Dependency supply-chain compromise | all | Pinned versions + lockfiles; `pip-audit`, `npm audit`, `cargo audit` in CI | **M1** (CI) |
| T21 | Self-upgrade introduces backdoor | A6 | Self-modification on isolated branch, full test + security scan, user approval, signed package | M16 |
| T22 | Repudiation of approvals | A5 | Approvals recorded with user id, timestamp, nonce in hash-chained audit | M7 |
| T23 | Denial of service of local service | B1 | Request size limits; rate limiting per connection | M17 |
| T25 | Tampered speech model on disk | A6 | Models load from the user's own data directory with `local_files_only`; Hugging Face downloads are TLS-protected and pinned to a repository; hash pinning of model files is planned with signed updates | M3 (partial) / M16 |
| T24 | Global hotkey abused by another app to open the mic | B1/B6 | Hotkey only starts capture through the authenticated service, which still enforces mute/privacy; capture is visible and audited; auto-close after max duration | **M2** |

## 4. Residual risks (accepted, documented)

- A process running **as the same Windows user** with debugging rights can read JACK's memory.
  Out of scope: OS user boundary is the security boundary for a desktop app.
- Loopback traffic is plaintext HTTP. Acceptable because it never leaves the host and is
  token-authenticated; TLS applies to all external traffic.

## 5. Review cadence

The threat model is updated at every milestone that introduces a new boundary or tool.
