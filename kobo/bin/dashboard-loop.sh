#!/bin/sh
# dashboard-loop.sh — long-running loop that refreshes the dashboard.
# Launched in the background by NickelMenu (cmd_spawn) when the user taps
# the Dashboard menu item. Stays alive until reboot or until the file
# /mnt/onboard/.adds/dashboard/STOP is touched.

set -u

DIR="$(dirname "$(readlink -f "$0")")"
CONF="$DIR/dashboard.conf"
[ -f "$CONF" ] && . "$CONF"

: "${REFRESH_SECONDS:=3600}"   # one refresh per hour
: "${WIFI_WAIT_SECONDS:=120}"
: "${CACHE_DIR:=/mnt/onboard/.adds/dashboard/cache}"
: "${LOG:=$CACHE_DIR/dashboard.log}"
: "${STOP_FILE:=/mnt/onboard/.adds/dashboard/STOP}"

mkdir -p "$CACHE_DIR"
ts()  { date '+%F %T'; }
log() { echo "$(ts) loop: $*" >> "$LOG"; }

PID_FILE="$CACHE_DIR/loop.pid"
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    log "another loop already running (pid $(cat "$PID_FILE")); exiting"
    exit 0
fi
echo $$ > "$PID_FILE"
trap 'rm -f "$PID_FILE"' EXIT INT TERM

wait_for_wifi() {
    waited=0
    while [ $waited -lt "$WIFI_WAIT_SECONDS" ]; do
        if ip route 2>/dev/null | grep -q '^default '; then
            log "wifi ready after ${waited}s"
            return 0
        fi
        sleep 5
        waited=$((waited + 5))
    done
    log "wifi not ready after ${WIFI_WAIT_SECONDS}s; trying anyway"
    return 1
}

log "loop start, pid=$$"
wait_for_wifi || true
"$DIR/update-dashboard.sh" || log "initial update rc=$?"

while :; do
    if [ -f "$STOP_FILE" ]; then
        log "STOP file present, exiting"
        rm -f "$STOP_FILE"
        exit 0
    fi
    sleep "$REFRESH_SECONDS"
    wait_for_wifi || true
    "$DIR/update-dashboard.sh" || log "update rc=$?"
done
