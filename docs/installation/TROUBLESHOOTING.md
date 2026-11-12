# Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| Header shows `service restarting` repeatedly | The service crashes on start | Open `%LOCALAPPDATA%\ai.jack.desktop\logs\jack-service.log`. Use tray → **Restart JACK service** after fixing the cause |
| Header shows `service failed` | 5 consecutive failed starts | Check the log. Antivirus quarantining `jack-service.exe` is a known cause for unsigned builds: add an exclusion for the install folder or wait for signed builds |
| `live connecting` but service running | WebSocket blocked | A local firewall or proxy intercepting loopback traffic. Allow `127.0.0.1` for `JACK AI.exe` |
| SmartScreen "Windows protected your PC" | Installer is unsigned (0.1.0) | **More info** → **Run anyway**, only if the SHA-256 matches `BUILD-REPORT.json` |
| Audit page shows "Tampering detected" | `jack.db` was edited outside JACK | Keep a copy of the database for investigation. The chain cannot be repaired in place |
| Second launch does nothing | JACK is already running in the tray | Click the tray icon. Only one instance runs at a time |
| "No audio is arriving from the microphone" | Microphone access is blocked, or the device is in use or disconnected | Windows Settings → Privacy & security → Microphone: allow **desktop apps** to access the microphone. Close other apps that hold the device exclusively. Choose the device on the Voice page |
| Voice component shows `degraded – No microphone found` | Windows reports no capture device | Connect a microphone, then use **Refresh** on the Voice page |
| "Push-to-talk shortcut Ctrl+Shift+Space is unavailable" | Another app registered the same hotkey | Close that app or change its hotkey, then restart JACK. The on-screen button works regardless |
| Hold-to-talk stops by itself | Maximum listening time reached | Raise it on the Voice page (up to 120 s) |

## Collecting diagnostics

The service writes logs to `%LOCALAPPDATA%\ai.jack.desktop\logs\`. Tokens, API keys, GitHub
tokens and private keys are redacted before anything is written, but review logs before
sharing them anyway.
