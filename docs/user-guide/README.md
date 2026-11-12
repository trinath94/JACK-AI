# User Guide (0.1.0 developer preview — Milestone 3)

## What works today

- **Home dashboard**:
  - The JACK orb reacts to your voice while you hold push-to-talk.
  - Microphone status, and a command box (Ctrl+K) that records typed commands as durable tasks.
  - The current task with its timeline, and recent tasks.
  - Live CPU, memory and disk use.
  - Recent events and component health.
  - The approval queue and integrations are shown as not yet available, each with the milestone that delivers it.
- **Talking to JACK**: first open **Voice Assistant → Speech models** and download `small.en`
  (commands) and `tiny.en` (wake word). They run offline on your computer once downloaded.
  - **Push-to-talk**: hold **Ctrl+Shift+Space** anywhere in Windows, or the button on Home, and speak.
  - **Wake word**: turn on *Listen for "Jack"* on the Voice page. Say **"Jack"** (or "Hey Jack"), wait
    for *"Yes, I'm listening"*, then give the command. You can also say it in one go: *"Jack, open GitHub."*
  - JACK turns what you said into a task, tells you so, and shows *You / JACK* on the Home page.
    > JACK records your command as a task but cannot plan or carry it out yet; that arrives in
    > Milestones 5–7. JACK says this in its reply.
  - Press push-to-talk while JACK is speaking to interrupt it.
- **Voice Assistant settings**: microphone, mute, privacy mode, push-to-talk limit;
  wake word on or off and sensitivity; command model (accurate `small.en` or faster `base.en` / `tiny.en`);
  how long a pause ends a command; spoken replies, voice and speed; conversation history.
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

- Audio never leaves your computer and is never saved. Speech recognition and the wake word run locally.
- With the wake word on, the microphone stays open so JACK can hear "Jack". Everything else it hears
  is discarded immediately. The header shows *wake word on*, and the tray tooltip says *listening for "Jack"*.
- Only the **text** of conversations is kept, for 30 days by default. Turn it off, shorten it, or clear it on the Voice page.
- **Mute**: the microphone stays off until you unmute it (the tray menu or the Voice page).
- **Privacy mode**: the microphone is off, nothing is transcribed or kept, and JACK doesn't speak.
- The service enforces both settings, so neither the hotkey nor any other client can open the microphone while they're on.
- Every time the microphone opens and closes is listed on the Security page.

## Not available yet

Claude integration (M4); requirement discovery: JACK asking follow-up questions (M5); approvals (M6);
agents and task execution (M7); GitHub (M9); servers (M10); deployments (M13); creative studio (M14).
Each one is labelled in the app with its milestone.
