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
| JACK says "I can't understand speech yet" | No speech model is downloaded | Voice page → Speech models → download `small.en` (or `base.en` on slower PCs), plus `tiny.en` for the wake word |
| Model download shows an error | No internet access to huggingface.co, or a proxy or firewall blocks it | Allow `huggingface.co` and `*.hf.co`, then press **Retry**. Recognition itself works offline once the download completes |
| "Jack" is not recognised | Wake-word sensitivity too low, a noisy room, or an accent the small wake model struggles with | Raise the sensitivity, speak a little slower ("Hey… Jack"), or use push-to-talk. See the evaluation in the Milestone 3 report |
| JACK wakes up when nobody called it | A sentence starting with a similar word ("Jackson…") | Lower the sensitivity. The wake word only triggers at the start of an utterance |
| No spoken replies | Spoken replies are off, no Windows voices are installed, or there is no audio output | Voice page → Spoken replies → Test voice. Windows Settings → Time & language → Speech → add voices |
| First command after start-up is slow | Models are still loading | Wait a few seconds after JACK starts; later commands are faster |

## Collecting diagnostics

The service writes logs to `%LOCALAPPDATA%\ai.jack.desktop\logs\`. Tokens, API keys, GitHub
tokens and private keys are redacted before anything is written, but review logs before
sharing them anyway.
