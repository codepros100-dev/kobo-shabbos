#!/bin/sh
# show-dashboard.sh — fetch+render the dashboard, then SUSPEND Nickel so the
# image stays on screen indefinitely. To return to the library, power-cycle
# the Kobo (long-press power, off, on).
#
# This is the "Shabbos display mode" entry point. Nickel comes back on reboot.

set -u

DIR="$(dirname "$(readlink -f "$0")")"
CONF="$DIR/dashboard.conf"
[ -f "$CONF" ] && . "$CONF"

: "${CACHE_DIR:=/mnt/onboard/.adds/dashboard/cache}"
: "${LOG:=$CACHE_DIR/dashboard.log}"

mkdir -p "$CACHE_DIR"
ts()  { date '+%F %T'; }
log() { echo "$(ts) show: $*" >> "$LOG"; }

log "step 1: running update-dashboard to fetch + initial render"
"$DIR/update-dashboard.sh"
rc=$?
log "update-dashboard returned rc=$rc"

# Even on rc=2 (renderer failed) we may still want to try again after suspend.
if [ "$rc" -eq 1 ]; then
    log "abort: fetch failed and no cached image; leaving Nickel alive"
    exit 1
fi

PNG="${CACHE_DIR}/dashboard.png"
if [ ! -s "$PNG" ]; then
    log "abort: no cached PNG at $PNG"
    exit 1
fi

# Suspend Nickel BEFORE the final render so it can't redraw over us.
log "step 2: suspending Nickel"
suspend_nickel() {
    if command -v killall >/dev/null 2>&1; then
        killall -STOP nickel 2>>"$LOG" && return 0
    fi
    pid=$(pidof nickel 2>/dev/null)
    [ -z "$pid" ] && pid=$(ps | awk '/[n]ickel/ {print $1; exit}')
    if [ -n "$pid" ]; then
        kill -STOP "$pid" 2>>"$LOG" && return 0
    fi
    return 1
}
suspend_nickel && log "nickel suspended" || log "WARN: could not suspend nickel"

# Re-render now that Nickel can't fight us.
log "step 3: re-rendering with Nickel frozen"
if [ -x /usr/local/Kobo/pickel ]; then
    /usr/local/Kobo/pickel showpic "$PNG" >>"$LOG" 2>&1 \
        && log "final render via pickel showpic" \
        || log "pickel returned $?"
fi

log "show-dashboard done; power-cycle the Kobo to return to library"
