#!/usr/bin/env bash
# End-to-end smoke test of the RELEASE desktop build under a virtual display (Linux).
#
# Proves, against the real binaries:
#   1. the app launches and the supervisor starts the bundled sidecar
#   2. the service migrates its database and the main window renders live status
#   3. a command typed into the UI (focused with Ctrl+K) becomes a durable task
#   4. the service is restarted after being SIGKILLed, with a fresh audit record
#   5. closing the window keeps JACK running (tray)
#   6. quitting gracefully (SIGTERM) leaves no service processes
#   7. even if the app is SIGKILLed, the service shuts itself down (lifeline)
#   8. the audit hash chain is intact afterwards
#   9. (VOICE_E2E=1) holding the global hotkey Ctrl+Shift+Space while synthesised speech
#      plays into a virtual PulseAudio microphone captures it; releasing closes the mic;
#      with speech models (JACK_MODELS_DIR) the command becomes a voice task
#  10. (VOICE_E2E=1 + models) with the wake word on, "Hey Jack." → spoken reply →
#      "Create a professional company logo." becomes a wake-triggered voice task
#  11. (AI_E2E=1) Usage and Billing: an Anthropic API key typed into the UI is stored (never
#      written to the database or logs), "Test connection" reaches a local fake Messages
#      API with the key as a Bearer token, and the call is recorded with an estimated cost
#
# Usage: [VOICE_E2E=1] [AI_E2E=1] tests/e2e/linux_smoke.sh <jack-ai binary> <output dir>
# Requires: Xvfb, openbox, wmctrl, xdotool, imagemagick (import), dbus, python3;
#           for VOICE_E2E=1 also pulseaudio, pulseaudio-utils, libasound2-plugins, sox.
set -uo pipefail

APP="$(realpath "$1")"
OUT="$(realpath -m "$2")"
BIN_DIR="$(dirname "$APP")"
mkdir -p "$OUT"
export DISPLAY=:97
export XDG_DATA_HOME="$OUT/xdg-data" XDG_CONFIG_HOME="$OUT/xdg-config"
export WEBKIT_DISABLE_COMPOSITING_MODE=1 NO_AT_BRIDGE=1
DB="$XDG_DATA_HOME/ai.jack.desktop/data/jack.db"
HAVE_MODELS=0
if [[ -n "${JACK_MODELS_DIR:-}" ]] && ls -d "$JACK_MODELS_DIR"/models--Systran--faster-whisper-{tiny,small}.en/snapshots/* >/dev/null 2>&1; then
  HAVE_MODELS=1; export JACK_MODELS_DIR
fi
say() {  # say "<text>": synthesise and play into the virtual microphone
  espeak-ng -v en-us -s 150 -w "$OUT/say.wav" "$1" && paplay -d jackvirt "$OUT/say.wav"
}
PASS=0; FAIL=0
ok()  { echo "PASS  $*"; PASS=$((PASS+1)); }
bad() { echo "FAIL  $*"; FAIL=$((FAIL+1)); }
wait_until() { local t=$1; shift; for _ in $(seq 1 $((t*4))); do "$@" && return 0; sleep 0.25; done; return 1; }
all_service_pids() { pgrep -f "^$BIN_DIR/jack-service" || true; }
service_pid() { pgrep -P "$1" -f "jack-service" | head -1; }   # direct child of the app
q() { python3 -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute(sys.argv[2]).fetchone()[0])" "$DB" "$1" 2>/dev/null || echo 0; }
q_ge() { [[ "$(q "$1")" -ge "$2" ]]; }
no_services() { [[ -z "$(all_service_pids)" ]]; }
start_app() { "$APP" >> "$OUT/app.log" 2>&1 & APP_PID=$!; }

if [[ -n "$(all_service_pids)" ]]; then echo "stale jack-service processes running; aborting"; exit 2; fi

AI_KEY="sk-ant-api03-$(printf 'T%.0s' $(seq 1 40))"  # the fake API's accepted test key
if [[ "${AI_E2E:-0}" == 1 ]]; then
  REPO="$(cd "$(dirname "$0")/../.." && pwd)"
  uv run --project "$REPO/services/api" python "$REPO/tests/e2e/run_fake_anthropic.py" "$OUT/fake_api.url" \
    > "$OUT/fake_api.log" 2>&1 & FAKE_API=$!
  wait_until 30 test -s "$OUT/fake_api.url"
  export JACK_ANTHROPIC_BASE_URL="$(cat "$OUT/fake_api.url")"
  # Linux CI has no OS keyring; this opt-in test store is shown in the UI as "not secure".
  export JACK_INSECURE_TEST_CREDENTIALS=1
fi

if [[ "${VOICE_E2E:-0}" == 1 ]]; then
  # Virtual microphone: a null sink whose monitor is remapped as a capture source, routed to
  # ALSA's default device so PortAudio (inside the frozen service) uses it like a real mic.
  pactl info >/dev/null 2>&1 || pulseaudio -D --exit-idle-time=-1 2>/dev/null
  wait_until 10 bash -c "pactl info >/dev/null 2>&1"
  pactl list short sinks | grep -q jackvirt || pactl load-module module-null-sink sink_name=jackvirt >/dev/null
  pactl list short sources | grep -q jackmic || pactl load-module module-remap-source master=jackvirt.monitor source_name=jackmic >/dev/null
  pactl set-default-source jackmic
  # A null sink suspends when idle and its monitor then delivers no frames at all; a real
  # microphone never does that, so keep the virtual device running.
  pactl unload-module module-suspend-on-idle 2>/dev/null || true
  SRV="$(pactl info | sed -n 's/^Server String: //p')"
  [[ "$SRV" == unix:* || "$SRV" == tcp:* ]] || SRV="unix:$SRV"
  export PULSE_SERVER="$SRV"
  # HOME changes below (for .asoundrc); keep the PulseAudio auth cookie reachable.
  [[ -f "$HOME/.config/pulse/cookie" ]] && export PULSE_COOKIE="$HOME/.config/pulse/cookie"
  export HOME="$OUT/home"; mkdir -p "$HOME"
  printf 'pcm.!default { type pulse }\nctl.!default { type pulse }\n' > "$HOME/.asoundrc"
fi

Xvfb "$DISPLAY" -screen 0 1440x900x24 >/dev/null 2>&1 & XVFB=$!
sleep 1
eval "$(dbus-launch --sh-syntax)"
openbox >/dev/null 2>&1 & WM=$!
trap 'kill ${APP_PID:-} ${FAKE_API:-} $WM $XVFB $DBUS_SESSION_BUS_PID 2>/dev/null; pkill -f "^$BIN_DIR/jack-service" 2>/dev/null; true' EXIT
sleep 1

# 1–2: launch
start_app
wait_until 60 bash -c "pgrep -P $APP_PID -f jack-service >/dev/null" \
  && ok "supervisor started bundled sidecar (pid $(service_pid $APP_PID))" || bad "sidecar not started"
wait_until 60 q_ge "select count(*) from audit_events where action='service.start'" 1 \
  && ok "service started and migrated the database" || bad "database not initialised"
WIN=""
wait_until 30 bash -c 'xdotool search --name "^JACK AI$" >/dev/null' && WIN=$(xdotool search --name "^JACK AI$" | head -1)
[[ -n "$WIN" ]] && ok "main window shown" || bad "main window not found"
sleep 6   # WebView connects its WebSocket and renders
import -window root "$OUT/01-home.png"

# 3: typed command -> durable task (Ctrl+K focuses the command box)
if [[ -n "$WIN" ]]; then
  xdotool windowactivate --sync "$WIN" 2>/dev/null || true
  xdotool key ctrl+k
  sleep 0.5
  xdotool type --delay 20 "Jack, build a professional corporate website"
  xdotool key Return
  wait_until 15 q_ge "select count(*) from tasks where command_text like '%corporate website%'" 1 \
    && ok "typed command persisted as task ($(q "select status from tasks limit 1"))" \
    || bad "typed command not persisted"
  sleep 1.5
  import -window root "$OUT/02-task-created.png"
fi

# 11: AI provider setup through the UI against a local fake Anthropic API
if [[ "${AI_E2E:-0}" == 1 && -n "$WIN" ]]; then
  xdotool windowactivate --sync "$WIN" 2>/dev/null || true
  xdotool key ctrl+5; sleep 2
  import -window root "$OUT/08-usage-before.png"
  # Window-relative position of the key field (calibrated on the 08 shot).
  xdotool mousemove --window "$WIN" "${AI_KEY_X:-487}" "${AI_KEY_Y:-572}" click 1
  xdotool type --delay 5 "$AI_KEY"
  xdotool key Return
  wait_until 15 q_ge "select count(*) from audit_events where action='credential.set'" 1 \
    && ok "API key saved from the UI (audited as credential.set)" || bad "API key not saved"
  sleep 2
  import -window root "$OUT/08b-key-saved.png"
  # Saving a key moves keyboard focus to "Test connection" (no layout-dependent click).
  xdotool key space
  wait_until 30 q_ge "select count(*) from usage_records where purpose='connection_test' and succeeded=1" 1 \
    && ok "Test connection reached the (fake) Anthropic API and was recorded" || bad "connection test not recorded"
  COST=$(q "select cost_usd from usage_records where purpose='connection_test' and succeeded=1 limit 1")
  [[ -n "$COST" && "$COST" != 0 ]] && ok "usage recorded with an estimated cost (\$$COST)" || bad "no cost recorded"
  LAST=$(tail -1 "$OUT/fake_api.requests.jsonl" 2>/dev/null)
  [[ "$LAST" == *'"bearer_present": true'* && "$LAST" == *'"fallbacks": "default"'* ]] \
    && ok "API received the stored key as a Bearer token, with refusal fallback on" || bad "unexpected API request: $LAST"
  if grep -aq "$AI_KEY" "$DB" "$DB"-wal "$OUT/app.log" "$XDG_DATA_HOME/ai.jack.desktop/logs/"* 2>/dev/null; then
    bad "API key found in the database or logs"
  else
    ok "API key appears nowhere in the database or logs"
  fi
  sleep 1
  import -window root "$OUT/09-usage-after.png"
  xdotool key ctrl+1; sleep 1
fi

# 9: global hotkey push-to-talk with real audio capture
if [[ "${VOICE_E2E:-0}" == 1 && -n "$WIN" ]]; then
  MIC0=$(grep -c "microphone delivering audio" "$OUT/app.log" || true)
  xdotool keydown ctrl+shift+space
  # Virtual devices can take a moment to start; speak once audio is flowing.
  wait_until 5 bash -c "[[ \$(grep -c 'microphone delivering audio' '$OUT/app.log') -gt $MIC0 ]]" || true
  sleep 0.2
  say "Build a professional corporate website." & SAY=$!
  sleep 1.2
  import -window root "$OUT/04-listening.png"
  wait $SAY
  sleep 1.0
  xdotool keyup ctrl+shift+space
  wait_until 10 q_ge "select count(*) from audit_events where action='voice.capture.stop'" 1 || true
  SRC=$(q "select json_extract(details,'$.source') from audit_events where action='voice.capture.start' order by seq desc limit 1")
  [[ "$SRC" == hotkey ]] && ok "global hotkey Ctrl+Shift+Space opened the microphone (source=$SRC)" || bad "hotkey capture not started (source=$SRC)"
  MS=$(q "select json_extract(details,'$.captured_ms') from audit_events where action='voice.capture.stop' order by seq desc limit 1")
  BY=$(q "select json_extract(details,'$.stopped_by') from audit_events where action='voice.capture.stop' order by seq desc limit 1")
  [[ "$BY" == released && "${MS:-0}" -ge 2500 ]] && ok "releasing the hotkey closed the microphone after ${MS} ms" || bad "capture stop: by=$BY ms=$MS"
  NOAUDIO=$(q "select count(*) from notifications where kind='voice.no_audio'")
  [[ "$NOAUDIO" == 0 ]] && ok "real audio levels arrived from the virtual microphone (no-audio watchdog silent)" || bad "no audio reached the service"
  if [[ $HAVE_MODELS == 1 ]]; then
    wait_until 60 q_ge "select count(*) from tasks where source='voice'" 1 || true
    CMD=$(q "select command_text from tasks where source='voice' order by created_at desc limit 1")
    [[ "${CMD,,}" == *"corporate website"* ]] && ok "spoken command recognised and saved as a voice task: \"$CMD\"" \
      || bad "spoken command not recognised (got: $CMD)"
    TURNS=$(q "select count(*) from voice_turns")
    [[ "${TURNS:-0}" -ge 2 ]] && ok "conversation history recorded ($TURNS turns)" || bad "no conversation history"
  else
    echo "SKIP  speech recognition (set JACK_MODELS_DIR with tiny.en and small.en)"
  fi
  sleep 3
  import -window root "$OUT/05-after-capture.png"
  xdotool windowactivate --sync "$WIN" 2>/dev/null || true
  xdotool key ctrl+4; sleep 2
  import -window root "$OUT/06-voice-page.png"
  xdotool key ctrl+1; sleep 1
fi

# 4: crash recovery
OLD=$(service_pid $APP_PID)
kill -9 "$OLD"
wait_until 45 bash -c "p=\$(pgrep -P $APP_PID -f jack-service | head -1); [[ -n \"\$p\" && \"\$p\" != $OLD ]]" \
  && ok "service restarted after SIGKILL (old $OLD, new $(service_pid $APP_PID))" || bad "service not restarted"
wait_until 30 q_ge "select count(*) from audit_events where action='service.start'" 2 \
  && ok "audit records $(q "select count(*) from audit_events where action='service.start'") service starts" \
  || bad "no audit record for restarted service"
wait_until 15 bash -c "[[ \$(pgrep -f '^$BIN_DIR/jack-service' | wc -l) -le 2 ]]" \
  && ok "old service tree exited (no orphan after crash)" || bad "orphan after crash: $(all_service_pids | tr '\n' ' ')"
sleep 5
import -window root "$OUT/03-after-restart.png"

# 5: close-to-tray (WM_DELETE_WINDOW via the window manager, like the title-bar X button)
wmctrl -c "JACK AI" || true
sleep 2
kill -0 "$APP_PID" 2>/dev/null && ok "app still running after window close (tray)" || bad "app exited on window close"

# 6: graceful quit
kill -TERM "$APP_PID"; wait "$APP_PID" 2>/dev/null
wait_until 15 no_services && ok "no service processes after SIGTERM quit" || bad "orphaned service after quit: $(all_service_pids | tr '\n' ' ')"

# 10 + 7: relaunch (wake word pre-enabled when testing voice), then hard-kill the app
if [[ "${VOICE_E2E:-0}" == 1 && $HAVE_MODELS == 1 ]]; then
  # Equivalent to the user having turned the wake word on in a previous session.
  python3 - "$DB" <<'PY'
import sqlite3, sys, json, datetime
c = sqlite3.connect(sys.argv[1])
c.execute("insert or replace into settings(key, value, updated_at) values ('voice', ?, ?)",
          (json.dumps({"wake_word_enabled": True}), datetime.datetime.now(datetime.UTC).isoformat()))
c.commit()
PY
fi
start_app
wait_until 60 bash -c "pgrep -P $APP_PID -f jack-service >/dev/null" || true
wait_until 60 q_ge "select count(*) from audit_events where action='service.start'" 3 || true
if [[ "${VOICE_E2E:-0}" == 1 && $HAVE_MODELS == 1 ]]; then
  wait_until 60 q_ge "select count(*) from audit_events where action='voice.standby.start'" 1 \
    && ok "wake word standby started after relaunch (setting persisted)" || bad "wake word standby not started"
  wait_until 15 bash -c "[[ \$(grep -c 'microphone delivering audio' '$OUT/app.log') -ge 1 ]]" || true
  sleep 4  # models load in the background after start-up
  WAKES=$(q "select count(*) from audit_events where action='voice.wake'")
  say "Hey Jack."
  wait_until 20 q_ge "select count(*) from audit_events where action='voice.wake'" $((WAKES + 1)) \
    && ok "spoken \"Hey Jack\" detected by the wake word engine" || bad "wake word not detected"
  sleep 3.5  # JACK says "Yes, I'm listening." (into the same virtual mic: echo suppression)
  W=$(xdotool search --name "^JACK AI$" | head -1); [[ -n "$W" ]] && import -window root "$OUT/07-wake-listening.png"
  say "Create a professional company logo."
  wait_until 60 bash -c "python3 -c \"import sqlite3,sys;sys.exit(0 if sqlite3.connect('$DB').execute(\\\"select count(*) from tasks where source='voice' and lower(command_text) like '%logo%'\\\").fetchone()[0] else 1)\"" \
    && ok "wake-word command saved as a voice task: \"$(q "select command_text from tasks where lower(command_text) like '%logo%' limit 1")\"" \
    || bad "wake-word command not recognised"
  TRIG=$(q "select trigger from voice_sessions order by started_at desc limit 1")
  [[ "$TRIG" == wake ]] && ok "conversation recorded as a wake-word session" || bad "last session trigger: $TRIG"
fi
kill -9 "$APP_PID"; wait "$APP_PID" 2>/dev/null
wait_until 15 no_services && ok "service shut itself down after the app was SIGKILLed" \
  || bad "orphaned service after app SIGKILL: $(all_service_pids | tr '\n' ' ')"

# 8: audit chain
CHAIN=$(python3 - "$DB" <<'EOF'
import sqlite3, sys
rows = sqlite3.connect(sys.argv[1]).execute("select seq, prev_hash, hash from audit_events order by seq").fetchall()
linked = all(r[1] == ("0" * 64 if i == 0 else rows[i - 1][2]) and r[0] == i + 1 for i, r in enumerate(rows))
print(("linked" if linked else "broken"), len(rows))
EOF
)
[[ "$CHAIN" == linked* ]] && ok "audit chain links intact ($CHAIN events)" || bad "audit chain: $CHAIN"

echo "----"; echo "passed=$PASS failed=$FAIL"
[[ $FAIL -eq 0 ]]
