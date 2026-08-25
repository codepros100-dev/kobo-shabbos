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

# Wait for default route (Nickel may have just been told to autoconnect WiFi).
: "${WIFI_WAIT_SECONDS:=60}"
wait_for_default_route() {
    waited=0
    while [ "$waited" -lt "$WIFI_WAIT_SECONDS" ]; do
        if ip route 2>/dev/null | grep -q '^default '; then
            [ "$waited" -gt 0 ] && log "wifi up after ${waited}s"
            return 0
        fi
        sleep 2
        waited=$((waited + 2))
    done
    log "no default route after ${WIFI_WAIT_SECONDS}s; trying fetch anyway"
    return 1
}
wait_for_default_route || true

# /mnt/onboard is FAT32 and may not preserve the +x bit. Copy fbink to /tmp
# (tmpfs, always executable) the first time we run, then use that.
TMP_FBINK="/tmp/fbink-dashboard"
if [ -f "$FBINK" ] && [ ! -x "$TMP_FBINK" ]; then
    cp "$FBINK" "$TMP_FBINK" 2>/dev/null && chmod +x "$TMP_FBINK" 2>/dev/null
fi
[ -x "$TMP_FBINK" ] && FBINK="$TMP_FBINK"

render() {
    img="$1"
    # pickel ships on every Kobo and reliably renders full-screen PNGs.
    # Try it first; the bundled fbink has image support compiled out.
    if [ -x /usr/local/Kobo/pickel ]; then
        /usr/local/Kobo/pickel showpic "$img" >>"$LOG" 2>&1 && {
            log "rendered via pickel showpic"
            return 0
        }
        log "pickel returned $?, trying fbink"
    fi
    if [ -x "$FBINK" ]; then
        "$FBINK" -q -c -g "file=$img,halign=CENTER,valign=CENTER" >>"$LOG" 2>&1 \
            && { log "rendered via bundled fbink"; return 0; }
        log "bundled fbink returned $? (image support may be disabled)"
    fi
    if command -v fbink >/dev/null 2>&1; then
        fbink -q -c -g "file=$img,halign=CENTER,valign=CENTER" >>"$LOG" 2>&1 \
            && { log "rendered via system fbink"; return 0; }
        log "system fbink returned $?"
    fi
    log "ERROR: no working renderer"
    return 2
}

TMP="$CACHE_DIR/dashboard.new.png"
DST="$CACHE_DIR/dashboard.png"

# Stock Kobo busybox sh has neither curl nor wget on PATH for spawned shells.
# Try every common location + a busybox subcommand. https-capable wins.
fetch() {
    url="$1" out="$2"
    for c in /usr/bin/curl /usr/local/bin/curl curl; do
        [ -x "$c" ] || command -v "$c" >/dev/null 2>&1 || continue
        if "$c" --fail --silent --show-error --max-time 60 \
               -H 'Cache-Control: no-cache' -o "$out" "$url" 2>>"$LOG"; then
            log "fetched via $c"
            return 0
        fi
        log "$c failed rc=$?"
    done
    for w in /usr/bin/wget /usr/local/bin/wget wget; do
        [ -x "$w" ] || command -v "$w" >/dev/null 2>&1 || continue
        if "$w" -q --no-check-certificate -O "$out" "$url" 2>>"$LOG"; then
            log "fetched via $w"
            return 0
        fi
        log "$w failed rc=$?"
    done
    if command -v busybox >/dev/null 2>&1; then
        if busybox wget -q --no-check-certificate -O "$out" "$url" 2>>"$LOG"; then
            log "fetched via busybox wget"
            return 0
        fi
        log "busybox wget failed rc=$?"
    fi
    return 1
}

log "fetching $DASHBOARD_URL"
if ! fetch "$DASHBOARD_URL" "$TMP"; then
    log "fetch failed (no working downloader or network down)"
    log "PATH=$PATH"
    log "have: curl=$(command -v curl 2>&1) wget=$(command -v wget 2>&1) busybox=$(command -v busybox 2>&1)"
    log "/usr/bin: $(ls /usr/bin/curl /usr/bin/wget 2>&1)"
    if [ ! -s "$DST" ]; then
        exit 1
    fi
    log "rendering last cached image"
else
    [ -s "$TMP" ] && mv "$TMP" "$DST"
fi

log "rendering $DST"
render "$DST" || { log "render failed"; exit 2; }
log "ok"
