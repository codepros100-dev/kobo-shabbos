#!/bin/sh
# dashboard-loop.sh — long-running loop that refreshes the dashboard.
# Run from KFMon at boot or via NickelMenu.
#
# It does NOT kill Nickel; Nickel keeps managing WiFi and power. We just
# repaint the framebuffer on top. After a Nickel screen change the user can
# re-launch us via the Dashboard icon (KFMon trigger).

set -u

DIR="$(dirname "$(readlink -f "$0")")"
CONF="$DIR/dashboard.conf"
[ -f "$CONF" ] && . "$CONF"

: "${REFRESH_SECONDS:=3600}"   # how often to fetch & redraw (1 hour)
: "${REPAINT_SECONDS:=300}"    # how often to repaint the cached image
: "${WIFI_WAIT_SECONDS:=120}"  # how long to wait for WiFi after boot
: "${LOG:=/mnt/onboard/.adds/dashboard/cache/dashboard.log}"

mkdir -p "$(dirname "$LOG")"
ts() { date '+%F %T'; }
log() { echo "$(ts) loop: $*" >> "$LOG"; }

# Wait for WiFi (interface up + a usable default route).
wait_for_wifi() {
    waited=0
    while [ $waited -lt "$WIFI_WAIT_SECONDS" ]; do
        if ip route | grep -q '^default '; then
            log "wifi ready (waited ${waited}s)"
            return 0
        fi
        sleep 5
        waited=$((waited + 5))
    done
    log "wifi NOT ready after ${WIFI_WAIT_SECONDS}s, will try anyway"
    return 1
}

log "boot. PID=$$"
wait_for_wifi || true

# Initial fetch + render
"$DIR/update-dashboard.sh" || log "initial update returned $?"

last_fetch=$(date +%s)
while :; do
    sleep "$REPAINT_SECONDS"
    now=$(date +%s)
    if [ $((now - last_fetch)) -ge "$REFRESH_SECONDS" ]; then
        wait_for_wifi || true
        if "$DIR/update-dashboard.sh"; then
            last_fetch=$now
        else
            log "fetch failed, will retry next cycle"
        fi
    else
        # Just repaint the cached PNG so any Nickel redraw gets covered
        if [ -s /mnt/onboard/.adds/dashboard/cache/dashboard.png ]; then
            "${FBINK:-$DIR/fbink}" -q -c \
                -g file=/mnt/onboard/.adds/dashboard/cache/dashboard.png,halign=CENTER,valign=CENTER \
                >>"$LOG" 2>&1 || log "repaint failed"
        fi
    fi
done
