#!/usr/bin/env bash
# End-to-end smoke test of the RELEASE desktop build under a virtual display (Linux).
#
# Proves, against the real binaries:
#   1. the app launches and the supervisor starts the bundled sidecar
#   2. the service migrates its database and the main window renders live status
#   3. a command typed into the UI becomes a durable task          (needs CMD_X/CMD_Y)
#   4. the service is restarted after being SIGKILLed, with a fresh audit record
#   5. closing the window keeps JACK running (tray)
#   6. quitting gracefully (SIGTERM) leaves no service processes
#   7. even if the app is SIGKILLed, the service shuts itself down (lifeline)
#   8. the audit hash chain is intact afterwards
#
# Usage: CMD_X=550 CMD_Y=468 tests/e2e/linux_smoke.sh <jack-ai binary> <output dir>
# CMD_X/CMD_Y: window-relative position of the Home command box (see 01-home.png).
# Requires: Xvfb, openbox, wmctrl, xdotool, imagemagick (import), dbus, python3.
set -uo pipefail

APP="$(realpath "$1")"
OUT="$(realpath -m "$2")"
BIN_DIR="$(dirname "$APP")"
mkdir -p "$OUT"
export DISPLAY=:97
export XDG_DATA_HOME="$OUT/xdg-data" XDG_CONFIG_HOME="$OUT/xdg-config"
export WEBKIT_DISABLE_COMPOSITING_MODE=1 NO_AT_BRIDGE=1
DB="$XDG_DATA_HOME/ai.jack.desktop/data/jack.db"
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

Xvfb "$DISPLAY" -screen 0 1440x900x24 >/dev/null 2>&1 & XVFB=$!
sleep 1
eval "$(dbus-launch --sh-syntax)"
openbox >/dev/null 2>&1 & WM=$!
trap 'kill ${APP_PID:-} $WM $XVFB $DBUS_SESSION_BUS_PID 2>/dev/null; pkill -f "^$BIN_DIR/jack-service" 2>/dev/null; true' EXIT
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

# 3: typed command -> durable task
if [[ -n "${CMD_Y:-}" && -n "$WIN" ]]; then
  xdotool windowactivate --sync "$WIN" 2>/dev/null || true
  xdotool mousemove --window "$WIN" "$CMD_X" "$CMD_Y" click 1
  xdotool type --delay 20 "Jack, build a professional corporate website"
  xdotool key Return
  wait_until 15 q_ge "select count(*) from tasks where command_text like '%corporate website%'" 1 \
    && ok "typed command persisted as task ($(q "select status from tasks limit 1"))" \
    || bad "typed command not persisted"
  sleep 1.5
  import -window root "$OUT/02-task-created.png"
else
  echo "SKIP  typed command (set CMD_X/CMD_Y)"
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

# 7: hard kill of the app itself
start_app
wait_until 60 bash -c "pgrep -P $APP_PID -f jack-service >/dev/null" || true
wait_until 60 q_ge "select count(*) from audit_events where action='service.start'" 3 || true
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
