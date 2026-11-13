# User Guide (0.1.0 developer preview — Milestone 5)

## What works today

- **Home dashboard**:
  - The JACK orb reacts to your voice while you hold push-to-talk.
  - Microphone status, and a command box (Ctrl+K). Type a request and JACK replies with its first
    question; the box then answers that conversation until it's done.
  - The current task with its timeline, and recent tasks.
  - Live CPU, memory and disk use.
  - Recent events and component health.
  - The approval queue and integrations are shown as not yet available, each with the milestone that delivers it.
- **Talking to JACK**: first open **Voice Assistant → Speech models** and download `small.en`
  (commands) and `tiny.en` (wake word). They run offline on your computer once downloaded.
  - **Push-to-talk**: hold **Ctrl+Shift+Space** anywhere in Windows, or the button on Home, and speak.
  - **Wake word**: turn on *Listen for "Jack"* on the Voice page. Say **"Jack"** (or "Hey Jack"), wait
    for *"Yes, I'm listening"*, then give the command. You can also say it in one go: *"Jack, open GitHub."*
  - JACK turns what you said into a task and starts asking what it needs to know (see
    **Requirement discovery** below). After a question it keeps listening for a few seconds, so you
    can just answer — no need to say "Jack" again.
  - Press push-to-talk while JACK is speaking to interrupt it.
- **Voice Assistant settings**: microphone, mute, privacy mode, push-to-talk limit;
  wake word on or off and sensitivity; command model (accurate `small.en` or faster `base.en` / `tiny.en`);
  how long a pause ends a command; spoken replies, voice and speed; conversation history.
- **Usage and Billing** (Ctrl+5): connect Claude.
  - **Anthropic API**: paste an API key from console.anthropic.com. It's stored in Windows Credential
    Manager and only a short hint is ever shown again. Choose the model and effort, then press **Test connection**.
    This is pay-as-you-go API billing, separate from a Claude Pro or Max subscription.
  - **Claude Code**: if Claude Code is installed and signed in (with a Claude plan or an API key), turn it on and
    press **Detect**. JACK runs Claude Code but never reads its sign-in details. Its usage is shown separately
    and never counted as API spend.
  - **Spending limits**: monthly, per task and per project (from Milestone 8), with alerts at 50/80/100% by default.
    JACK refuses API requests once a limit is reached.
  - **Fallback** to the other provider is off unless you turn it on.
  - **Test console**: ask Claude something and see the answer, the model, tokens and the estimated cost.
  > Once Claude is set up, requirement discovery uses it to understand your answers.
- **Requirement discovery — Command Centre** (Ctrl+6):
  - Say or type what you want, for example *"Jack, build a professional website."* JACK works out
    which of 19 kinds of job it is (website, web app, Windows/Android/iOS app, API, CRM, ERP, HRMS,
    trading, AI platform, image generation, photo editing, video, infrastructure, security audit,
    research, documentation, automation) and asks **one question at a time**, only the ones it needs.
  - Anything you already said is not asked again. Say **"you decide"** to take the usual choice,
    **"use defaults"** to skip the remaining questions, or **"cancel"** to stop.
  - If two answers can't both work (for example a site only on your PC that takes payments), JACK
    asks which one you want.
  - The result is a **specification**: requirements, assumptions (everything JACK chose for you,
    each changeable), scope and size, external services you'll need, hosting, and what JACK still
    needs to build it (with the milestone that delivers it).
  - Medium and large jobs wait for your approval ("Yes, go ahead" or **Approve specification**).
    Small jobs, like research or a single image, skip that step.
  - With Claude set up (Usage and Billing), JACK understands free-form answers better; otherwise it
    uses its own local rules. *How JACK asks* lets you choose local rules only, so nothing is sent
    to Claude.
  > After approval the task waits in *Planning*: planning and building start in later milestones,
  > and JACK says so.
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
| Ctrl+1 / 2 / 3 / 4 / 5 / 6 | Home / Active Tasks / Security / Voice Assistant / Usage and Billing / Command Centre |
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
- **After a question**, JACK listens for your answer for 8 seconds (shown as *Listening for your
  answer*). It never does this when muted or in privacy mode, and you can turn it off in the
  Command Centre.
- **What reaches Claude**: only the text of your requests and answers during requirement discovery,
  and only when Claude is set up and *Local rules only* is not chosen. Never audio.
- The service enforces both settings, so neither the hotkey nor any other client can open the microphone while they're on.
- Every time the microphone opens and closes is listed on the Security page.

## Not available yet

Planning and carrying out the work (M6–M7); approvals (M6);
agents and task execution (M7); GitHub (M9); servers (M10); deployments (M13); creative studio (M14).
Each one is labelled in the app with its milestone.
