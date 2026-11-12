# Installation Guide (pre-release)

> JACK AI 0.1.0 is a **Milestone 1 developer preview**. It installs and runs, but most of the
> assistant's capabilities are not implemented yet (see the Milestone 1 report).
> Installers are currently **unsigned**: Windows SmartScreen will warn before running them.

## Requirements

- Windows 10 (22H2) or Windows 11, x64
- About 300 MB of free disk space
- Microsoft Edge WebView2 Runtime. It ships with Windows 11; the installer adds it on Windows 10 if it is missing.

## Getting the installer

Installers are built by GitHub Actions (`Windows x64 build` job in `.github/workflows/ci.yml`).
Download the `jack-ai-windows-x64` artifact from a successful run. It contains:

- `JACK-AI-Setup-x64.exe` (NSIS)
- `JACK-AI-x64.msi` (WiX, for managed deployment)
- `BUILD-REPORT.json`, with SHA-256 checksums and the Authenticode status of each file

Check the checksum before installing:

```powershell
Get-FileHash .\JACK-AI-Setup-x64.exe -Algorithm SHA256
```

## Installing

- **EXE:** run `JACK-AI-Setup-x64.exe`. It installs for all users into `Program Files` and creates Start Menu and desktop shortcuts.
- **MSI (silent):** `msiexec /i JACK-AI-x64.msi /qn`

Neither installer needs Python, Node.js or Rust: the service is bundled as `jack-service.exe`.

## First launch

JACK opens its window and starts the local service. The header shows `service running` and
`live open` once the service is up. Closing the window keeps JACK in the system tray;
use the tray menu → **Quit JACK AI** to exit.

## Uninstalling

- Settings → Apps → Installed apps → **JACK AI** → Uninstall, or
- `msiexec /x JACK-AI-x64.msi /qn`

Uninstalling leaves your data in `%LOCALAPPDATA%\ai.jack.desktop`. Delete that folder to remove all tasks, audit history and logs.

## Not yet available in 0.1.0

Optional start with Windows, automatic updates and code signing are scheduled for Milestones 2, 16 and 18.
