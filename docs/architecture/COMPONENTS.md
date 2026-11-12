# JACK AI — Component Diagram

Deliverable 2 of Section 30. Solid boxes exist after Milestone 1; dashed (`:::planned`) are planned.

```mermaid
flowchart LR
  user((User<br/>voice / keyboard))

  subgraph desktop["JACK AI.exe — Tauri 2"]
    ui["React UI<br/>(WebView2)"]
    rust["Rust core<br/>tray · single-instance<br/>supervisor · token issuer"]
    audio["Native audio capture"]:::planned
    cred["Credential bridge<br/>(Windows Credential Manager)"]:::planned
    pwsh["Restricted PowerShell runner"]:::planned
  end

  subgraph svc["jack-service.exe — FastAPI on 127.0.0.1:ephemeral"]
    auth["Auth middleware<br/>token · Host · Origin"]
    api["REST /v1/*"]
    ws["WebSocket hub /v1/ws"]
    health["Health registry"]
    audit["Audit log"]
    tasks["Task store +<br/>state machine"]
    voice["Voice engine<br/>openWakeWord · VAD · Whisper · TTS"]:::planned
    orch["Chief Orchestrator<br/>LangGraph"]:::planned
    agents["17 agents<br/>schemas + tool allow-lists"]:::planned
    policy["Policy engine<br/>risk classes · approvals"]:::planned
    tools["Tool adapters<br/>git · ssh · docker · playwright"]:::planned
    mem["Project memory<br/>pgvector"]:::planned
    prov["Provider SDK<br/>Anthropic API · Claude Code"]:::planned
  end

  sqlite[("SQLite<br/>jack.db")]
  pg[("PostgreSQL + pgvector")]:::planned
  temporal["Temporal dev server"]:::planned
  updater["jack-updater.exe"]:::planned

  ext_gh["GitHub API"]:::planned
  ext_ssh["Ubuntu servers (SSH)"]:::planned
  ext_ai["Anthropic API / Claude Code"]:::planned
  ext_img["Image providers"]:::planned

  user --> ui
  user -. wake word .-> audio --> voice
  ui <-- "Tauri IPC (commands)" --> rust
  rust -- "spawn + env token" --> svc
  rust -- "/health/live probe" --> health
  ui -- "HTTPS-less loopback REST<br/>Bearer token" --> auth
  ui -- "WS first-frame auth" --> auth
  auth --> api & ws
  api --> tasks & health & audit
  ws --> health
  tasks --> sqlite
  audit --> sqlite
  api -.-> orch
  orch -.-> agents -.-> policy -.-> tools
  orch -.-> temporal
  orch -.-> prov -.-> ext_ai
  tools -.-> ext_gh & ext_ssh
  agents -.-> mem -.-> pg
  tools -.-> ext_img
  rust -.-> cred
  rust -.-> pwsh
  updater -.-> desktop

  classDef planned stroke-dasharray: 5 5,opacity:0.7
```

## Component responsibilities

| Component | Owns | Must never |
|---|---|---|
| React UI | Presentation, local view state | Persist secrets, call external services directly |
| Rust core | Process lifecycle, token issuance, OS integration, signature checks | Execute model-proposed commands without policy decision |
| Auth middleware | Token, Host and Origin validation, audit on failure | Log tokens |
| Health registry | Aggregated component status, change events | Block on a slow probe (each probe has a 2 s timeout) |
| Task store | Durable tasks + validated transitions | Allow a transition not in the state graph |
| Policy engine (M7) | Allow/deny/require-approval per tool call | Accept an approval not issued by the authenticated user |
| Orchestrator (M6–7) | Decomposition, scheduling, result review | Hold progress only in model context |
| Updater (M16) | Download, verify signature, swap install while app is stopped | Replace a running executable |
