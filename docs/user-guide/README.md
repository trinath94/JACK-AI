# User Guide (0.1.0 developer preview — Milestone 2)

## What works today

- **Home dashboard**:
  - The JACK orb reacts to your voice while you hold push-to-talk.
  - Microphone status, and a command box (Ctrl+K) that records typed commands as durable tasks.
  - The current task with its timeline, and recent tasks.
  - Live CPU, memory and disk use.
  - Recent events and component health.
  - The approval queue and integrations are shown as not yet available, each with the milestone that delivers it.
- **Voice Assistant**:
  - Choose your microphone, mute it, or turn on privacy mode.
  - Set the maximum listening time.
  - Test the microphone with a live level meter.
  - Save your wake-word preference and sensitivity. The wake word itself arrives in Milestone 3.
- **Push-to-talk**: hold the button on Home or the Voice page, or hold **Ctrl+Shift+Space**
  anywhere in Windows, even with JACK's window closed. The microphone opens only while you hold it
  and closes automatically after the maximum listening time.
  > Speech recognition arrives in Milestone 3. Until then JACK confirms how long it listened,
  > then discards the audio. Nothing is recorded or sent anywhere.
- **Notification centre** (bell icon): tasks that finish, fail, are cancelled or need input;
  components that degrade or recover; a microphone that opens but delivers no audio.
- **Active Tasks**: every task with its full timeline. Pause, resume and cancel are recorded permanently.
- **Security**: the tamper-evident audit log, including every time the microphone was opened.
- **Settings**: system, dark or light theme; accent colour; compact sidebar; **start JACK when you sign in to Windows**
  (JACK starts in the tray); a list of keyboard shortcuts.
- **System tray**: open JACK, **mute the microphone**, restart the service, or quit. Hover the icon to see the current voice state.

## Keyboard shortcuts

| Keys | Action |
|---|---|
| Ctrl+Shift+Space (hold) | Push-to-talk, anywhere in Windows |
| Ctrl+K | Type a command |
| Ctrl+1 / 2 / 3 / 4 | Home / Active Tasks / Security / Voice Assistant |
| Ctrl+, | Settings |
| Ctrl+B | Toggle compact sidebar |
| ? | Show all shortcuts |
| Esc | Close dialogs and panels |

If another application already uses Ctrl+Shift+Space, JACK shows an error and the on-screen button still works.

## Privacy

- **Mute**: the microphone stays off until you unmute it (the tray menu or the Voice page).
- **Privacy mode**: the microphone is off. From Milestone 3 it also stops transcripts being kept.
- The service enforces both settings, so neither the hotkey nor any other client can open the microphone while they're on.
- Every time the microphone opens and closes is listed on the Security page.

## Not available yet

The wake word "Jack", speech recognition and spoken replies (Milestone 3); Claude integration (M4);
requirement discovery (M5); approvals (M6); agents (M7); GitHub (M9); servers (M10);
deployments (M13); creative studio (M14). Each one is labelled in the app with its milestone.
