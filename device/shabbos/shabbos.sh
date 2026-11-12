#!/bin/sh
# Shabbos display for Kobo (Clara HD). Started from NickelMenu.
#
# Stops Nickel, then loops forever:
#   Wi-Fi up -> fetch live page -> (else today's offline page) -> paint
#   -> Wi-Fi down -> sleep until the next refresh (RTC wake).
# Leave: press the power button once. The device reboots into the normal UI.
#
# Everything uses absolute paths: NickelMenu starts us with cwd=/ and a
# minimal PATH, which is what broke the previous setup.

DIR=/mnt/onboard/.adds/shabbos
BIN="$DIR/bin"
LOG="$DIR/log.txt"
NILUJE=/usr/local/niluje/usbnet
export PATH="/sbin:/usr/sbin:/bin:/usr/bin:$NILUJE/bin:$NILUJE/sbin"
export LD_LIBRARY_PATH="$NILUJE/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# --- settings (override in $DIR/config) -------------------------------------
URL_BASE="https://raw.githubusercontent.com/codepros100-dev/kobo-shabbos/dashboard"
TZ="EST5EDT,M3.2.0,M11.1.0"
MAX_AGE=10800        # ignore a live page older than this many seconds
SLOT_MINUTE=25       # refresh at this minute of every hour
KEEP_AWAKE=0         # 1 = never suspend, keep Wi-Fi up (for testing over telnet)
NAP_OVERRIDE=""      # testing: fixed seconds between refreshes
MAX_CYCLES=0         # testing: leave (reboot) after this many refreshes; 0 = never
[ -f "$DIR/config" ] && . "$DIR/config"
[ -f "$DIR/DEBUG" ] && KEEP_AWAKE=1
export TZ

log() { echo "$(date '+%m-%d %H:%M:%S') $*" >>"$LOG"; }

# Run detached from NickelMenu's process group so killing Nickel can't take us down.
if [ "$1" != "--run" ]; then
    cp -f "$0" /tmp/shabbos.sh
    setsid /bin/sh /tmp/shabbos.sh --run >/dev/null 2>&1 &
    exit 0
fi

if [ -f /tmp/shabbos.pid ] && kill -0 "$(cat /tmp/shabbos.pid)" 2>/dev/null; then
    exit 0
fi
echo $$ >/tmp/shabbos.pid

# Keep the log small.
if [ -f "$LOG" ]; then tail -n 400 "$LOG" >/tmp/shabbos.log.new && cp -f /tmp/shabbos.log.new "$LOG"; fi
log "=== start (pid $$, keep_awake=$KEEP_AWAKE) ==="

# Binaries live on FAT (no exec bit guarantees), so run them from tmpfs.
mkdir -p /tmp/shabbos-bin
cp -f "$BIN/fbink" "$BIN/fbdepth" "$BIN/busybox_kobo" /tmp/shabbos-bin/ 2>>"$LOG"
chmod 755 /tmp/shabbos-bin/*
FBINK=/tmp/shabbos-bin/fbink
FBDEPTH=/tmp/shabbos-bin/fbdepth
BB=/tmp/shabbos-bin/busybox_kobo

# --- take over from Nickel ---------------------------------------------------
NICKEL_PID="$(pidof nickel | cut -d' ' -f1)"
if [ -n "$NICKEL_PID" ]; then
    # shellcheck disable=SC2046
    export $(tr '\0' '\n' <"/proc/$NICKEL_PID/environ" | grep -E '^(WIFI_MODULE|PLATFORM|INTERFACE|PRODUCT)=')
fi
: "${PLATFORM:=mx6sll-ntx}" "${WIFI_MODULE:=8189fs}" "${INTERFACE:=eth0}"
export PLATFORM WIFI_MODULE INTERFACE
log "platform=$PLATFORM wifi=$WIFI_MODULE if=$INTERFACE"

sync
killall -q -TERM nickel hindenburg sickel fickel strickel fontickel adobehost foxitpdf iink dhcpcd-dbus dhcpcd fmon
i=0
while pidof nickel >/dev/null && [ $i -lt 20 ]; do usleep 250000; i=$((i + 1)); done
rm -f /tmp/nickel-hardware-status
"$FBDEPTH" -d 8 -R UR >>"$LOG" 2>&1
grep -q '^nameserver' /etc/resolv.conf || echo "nameserver 1.1.1.1" >>/etc/resolv.conf

# --- power button watcher ------------------------------------------------------
# Any event on the gpio-keys device (power button / sleep cover) means "exit".
PWR_DEV=/dev/input/event0
: >/tmp/shabbos.pwr
cat "$PWR_DEV" >>/tmp/shabbos.pwr 2>/dev/null &
PWR_CAT=$!

button_pressed() { [ -s /tmp/shabbos.pwr ]; }

leave() {
    log "leaving (reboot)"
    kill "$PWR_CAT" 2>/dev/null
    [ -f "$DIR/exit.png" ] && paint "$DIR/exit.png"
    sync
    rm -f /tmp/shabbos.pid
    reboot
    exit 0
}

# --- helpers ---------------------------------------------------------------------
paint() {
    "$FBINK" -q -c -f -g "file=$1,valign=CENTER,halign=CENTER,h=-2,w=0" >>"$LOG" 2>&1
}

online() { ip route 2>/dev/null | grep -q '^default '; }

wifi_up() {
    online && return 0
    KMOD="/drivers/$PLATFORM/wifi"
    grep -q '^sdio_wifi_pwr ' /proc/modules || insmod "$KMOD/sdio_wifi_pwr.ko" 2>>"$LOG"
    usleep 250000
    grep -q "^$WIFI_MODULE " /proc/modules || insmod "$KMOD/$WIFI_MODULE.ko" 2>>"$LOG"
    sleep 1
    ifconfig "$INTERFACE" up 2>>"$LOG"
    pidof wpa_supplicant >/dev/null || wpa_supplicant -D wext -s -i "$INTERFACE" \
        -c /etc/wpa_supplicant/wpa_supplicant.conf -C /var/run/wpa_supplicant -B 2>>"$LOG"
    i=0
    while ! wpa_cli -i "$INTERFACE" status 2>/dev/null | grep -q 'wpa_state=COMPLETED'; do
        [ $i -ge 40 ] && { log "wifi: no association"; return 1; }
        sleep 1; i=$((i + 1))
    done
    if [ -x /sbin/dhcpcd ]; then
        dhcpcd -t 30 -w "$INTERFACE" >/dev/null 2>&1
    else
        udhcpc -S -i "$INTERFACE" -s /etc/udhcpc.d/default.script -n -q -t 10 >/dev/null 2>&1
    fi
    i=0
    while ! online; do
        [ $i -ge 20 ] && { log "wifi: no IP"; return 1; }
        sleep 1; i=$((i + 1))
    done
    return 0
}

wifi_down() {
    if [ -x /sbin/dhcpcd ]; then dhcpcd -k "$INTERFACE" >/dev/null 2>&1; fi
    killall -q udhcpc
    wpa_cli -i "$INTERFACE" terminate >/dev/null 2>&1
    ifconfig "$INTERFACE" down 2>/dev/null
    usleep 250000
    grep -q "^$WIFI_MODULE " /proc/modules && rmmod "$WIFI_MODULE" 2>>"$LOG"
    usleep 250000
    grep -q '^sdio_wifi_pwr ' /proc/modules && rmmod sdio_wifi_pwr 2>>"$LOG"
}

get() { # url, outfile
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --connect-timeout 15 --max-time 45 -o "$2" "$1" 2>>"$LOG" && return 0
    fi
    wget -q -T 30 --no-check-certificate -O "$2" "$1" 2>>"$LOG"
}

is_png() { [ "$(dd if="$1" bs=1 skip=1 count=3 2>/dev/null)" = "PNG" ]; }

# Sets IMG to a fresh live page, or returns 1.
fetch_live() {
    wifi_up || return 1
    rm -f /tmp/live.txt /tmp/live.png.new
    get "$URL_BASE/dashboard.txt?t=$(date +%s)" /tmp/live.txt || { log "fetch: stamp failed"; return 1; }
    stamp="$(tr -cd '0-9' </tmp/live.txt)"
    [ -n "$stamp" ] || { log "fetch: bad stamp"; return 1; }
    age=$(($(date +%s) - stamp))
    if [ "$age" -gt "$MAX_AGE" ] || [ "$age" -lt -3600 ]; then
        log "fetch: live page is stale (age ${age}s)"
        return 1
    fi
    get "$URL_BASE/dashboard.png?t=$stamp" /tmp/live.png.new || { log "fetch: image failed"; return 1; }
    is_png /tmp/live.png.new || { log "fetch: not a PNG"; return 1; }
    mv -f /tmp/live.png.new /tmp/live.png
    IMG=/tmp/live.png
    log "fetch: live page ok (age ${age}s)"
    return 0
}

seconds_to_next() {
    h=$(date +%H); m=$(date +%M); s=$(date +%S)
    h=${h#0}; m=${m#0}; s=${s#0}
    slot=$(( ((60 + SLOT_MINUTE - m) % 60) * 60 - s ))
    [ "$slot" -lt 300 ] && slot=$((slot + 3600))
    midnight=$(( (23 - h) * 3600 + (59 - m) * 60 + (60 - s) + 90 ))
    [ "$midnight" -lt "$slot" ] && slot=$midnight
    echo "$slot"
}

awake_wait() { # seconds; returns early (1) if the button is pressed
    end=$(($(date +%s) + $1))
    while [ "$(date +%s)" -lt "$end" ]; do
        button_pressed && return 1
        sleep 3
    done
    return 0
}

nap() { # seconds
    secs=$1
    if [ "$KEEP_AWAKE" = "1" ]; then
        awake_wait "$secs"; return
    fi
    sync
    t0=$(date +%s)
    # The kernel sometimes refuses the first attempt right after the Wi-Fi
    # module is unloaded, so try a few times before giving up.
    try=0
    while [ $try -lt 3 ]; do
        t1=$(date +%s)
        echo 1 >/sys/power/state-extended 2>>"$LOG"
        sleep 2
        "$BB" rtcwake -a -s "$((secs - (t1 - t0)))" -m mem >>"$LOG" 2>&1
        echo 0 >/sys/power/state-extended 2>>"$LOG"
        [ $(($(date +%s) - t1)) -ge 20 ] && break
        try=$((try + 1))
        sleep 5
    done
    slept=$(($(date +%s) - t0))
    log "nap: wanted ${secs}s, slept ${slept}s"
    sleep 1
    button_pressed && return 1
    # Woke early without the button (or could not suspend): wait it out awake.
    if [ $((secs - slept)) -gt 60 ]; then
        awake_wait $((secs - slept))
    fi
}

# --- main loop -------------------------------------------------------------------
hwclock -s -u 2>/dev/null
LAST=""
CYCLE=0
while :; do
    button_pressed && leave
    CYCLE=$((CYCLE + 1))
    if [ "$MAX_CYCLES" -gt 0 ] && [ "$CYCLE" -gt "$MAX_CYCLES" ]; then log "max cycles reached"; leave; fi
    IMG=""
    if ! fetch_live; then
        today="$DIR/pages/$(date +%Y-%m-%d).png"
        if [ -f "$today" ]; then
            IMG="$today"; log "showing offline page $(basename "$today")"
        else
            log "no offline page for $(date +%Y-%m-%d)"
        fi
    fi
    if [ -n "$IMG" ]; then
        sum="$(md5sum "$IMG" | cut -d' ' -f1)"
        if [ "$sum" != "$LAST" ]; then
            paint "$IMG" && LAST="$sum"
        fi
    elif [ -z "$LAST" ]; then
        "$FBINK" -q -c -f -m -M "Shabbos display: no page available. See .adds/shabbos/log.txt" >>"$LOG" 2>&1
    fi
    [ "$KEEP_AWAKE" = "1" ] || wifi_down
    nap "${NAP_OVERRIDE:-$(seconds_to_next)}" || leave
done
