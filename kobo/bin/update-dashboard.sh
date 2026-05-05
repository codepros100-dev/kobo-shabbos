#!/bin/sh
# update-dashboard.sh — fetch the latest dashboard PNG and paint it to the
# e-ink framebuffer. Designed for Kobo Clara HD running stock Nickel + KFMon.
#
# Exit codes:
#   0 success
#   1 fetch failed
#   2 fbink failed
#
# Configurable via env or the companion config file in the same directory.

set -eu

DIR="$(dirname "$(readlink -f "$0")")"
CONF="$DIR/dashboard.conf"
[ -f "$CONF" ] && . "$CONF"

: "${DASHBOARD_URL:=https://raw.githubusercontent.com/REPLACE_ME/REPLACE_ME/dashboard/dashboard.png}"
: "${CACHE_DIR:=/mnt/onboard/.adds/dashboard/cache}"
: "${FBINK:=$DIR/fbink}"
: "${LOG:=$CACHE_DIR/dashboard.log}"

mkdir -p "$CACHE_DIR"

ts() { date '+%F %T'; }
log() { echo "$(ts) $*" >> "$LOG"; }

# Ensure the binary exists (otherwise rely on PATH; KOReader ships fbink)
if [ ! -x "$FBINK" ]; then
    if command -v fbink >/dev/null 2>&1; then
        FBINK=fbink
    else
        log "ERROR: fbink not found at $FBINK and not on PATH"
        exit 2
    fi
fi

TMP="$CACHE_DIR/dashboard.new.png"
DST="$CACHE_DIR/dashboard.png"

log "fetching $DASHBOARD_URL"
if ! curl --fail --silent --show-error --max-time 60 \
        -H 'Cache-Control: no-cache' \
        -o "$TMP" "$DASHBOARD_URL" 2>>"$LOG"; then
    log "fetch failed"
    # fall back to last cached PNG if available
    if [ ! -s "$DST" ]; then
        exit 1
    fi
    log "rendering cached image"
else
    mv "$TMP" "$DST"
fi

# Render the PNG centered, scaled to fit, no flashing (less e-ink disturbance)
log "rendering $DST"
"$FBINK" -q -c -g "file=$DST,halign=CENTER,valign=CENTER" >>"$LOG" 2>&1 || {
    log "fbink failed"
    exit 2
}

log "ok"
