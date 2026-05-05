#!/bin/sh
# update-dashboard.sh — fetch the latest dashboard PNG and paint it to the
# e-ink framebuffer. Designed for Kobo Clara HD running stock Nickel.
#
# Renderer: prefers bundled fbink (extracted from KOReader), falls back to
# stock pickel showpic if fbink is missing or fails.
#
# Exit codes:
#   0 success
#   1 fetch failed (and no cached image)
#   2 render failed
#
# Configurable via env or the companion dashboard.conf file in the same dir.

set -u

DIR="$(dirname "$(readlink -f "$0")")"
CONF="$DIR/dashboard.conf"
[ -f "$CONF" ] && . "$CONF"

: "${DASHBOARD_URL:=https://raw.githubusercontent.com/codepros100-dev/kobo-shabbos/dashboard/dashboard.png}"
: "${CACHE_DIR:=/mnt/onboard/.adds/dashboard/cache}"
: "${FBINK:=$DIR/fbink}"
: "${LOG:=$CACHE_DIR/dashboard.log}"

mkdir -p "$CACHE_DIR"

ts()  { date '+%F %T'; }
log() { echo "$(ts) $*" >> "$LOG"; }

render() {
    img="$1"
    if [ -x "$FBINK" ]; then
        "$FBINK" -q -c -g "file=$img,halign=CENTER,valign=CENTER" >>"$LOG" 2>&1 \
            && return 0
        log "bundled fbink returned $?, trying fallback"
    fi
    if command -v fbink >/dev/null 2>&1; then
        fbink -q -c -g "file=$img,halign=CENTER,valign=CENTER" >>"$LOG" 2>&1 \
            && return 0
        log "system fbink returned $?, trying pickel"
    fi
    if [ -x /usr/local/Kobo/pickel ]; then
        /usr/local/Kobo/pickel showpic "$img" >>"$LOG" 2>&1 && return 0
        log "pickel returned $?"
    fi
    log "ERROR: no working renderer (tried bundled fbink, system fbink, pickel)"
    return 2
}

TMP="$CACHE_DIR/dashboard.new.png"
DST="$CACHE_DIR/dashboard.png"

log "fetching $DASHBOARD_URL"
if ! curl --fail --silent --show-error --max-time 60 \
        -H 'Cache-Control: no-cache' \
        -o "$TMP" "$DASHBOARD_URL" 2>>"$LOG"; then
    log "fetch failed"
    if [ ! -s "$DST" ]; then
        exit 1
    fi
    log "rendering last cached image"
else
    mv "$TMP" "$DST"
fi

log "rendering $DST"
render "$DST" || { log "render failed"; exit 2; }
log "ok"
