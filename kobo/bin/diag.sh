#!/bin/sh
# diag.sh — dumps device state to /mnt/onboard/.adds/dashboard/diag.log so we
# can see why the dashboard isn't drawing. Hardcodes paths intentionally so a
# busted env doesn't cause silent exits.
exec >/mnt/onboard/.adds/dashboard/diag.log 2>&1

echo "=== diag $(date) pid=$$ ==="
echo "user: $(id 2>&1)"
echo "pwd: $(pwd 2>&1)"
echo "PATH: $PATH"
echo "uname: $(uname -a 2>&1)"
echo
echo "=== filesystem ==="
mount | head -20
echo
echo "=== files in /mnt/onboard/.adds/dashboard ==="
ls -la /mnt/onboard/.adds/dashboard 2>&1
echo
echo "=== fbink binary check ==="
file /mnt/onboard/.adds/dashboard/fbink 2>&1
ls -la /mnt/onboard/.adds/dashboard/fbink 2>&1
echo "is executable from /mnt/onboard? "
[ -x /mnt/onboard/.adds/dashboard/fbink ] && echo "yes" || echo "no"
echo "does direct invoke work?"
/mnt/onboard/.adds/dashboard/fbink -v 2>&1 | head -3
echo
echo "=== /usr/local/Kobo binaries ==="
ls /usr/local/Kobo 2>&1 | head -30
echo
echo "=== pickel ==="
ls -la /usr/local/Kobo/pickel 2>&1
echo
echo "=== curl ==="
which curl
curl -V 2>&1 | head -1
echo
echo "=== network ==="
ip addr 2>&1 | head -20
echo
echo "ip route:"
ip route 2>&1
echo
echo "=== reachability test ==="
curl -fsI --max-time 15 https://raw.githubusercontent.com/codepros100-dev/kobo-shabbos/dashboard/dashboard.png 2>&1 | head -5
echo
echo "=== NickelMenu loaded? (libnm.so should be present) ==="
ls -la /usr/local/Kobo/imageformats/libnm.so 2>&1
echo
echo "=== NickelMenu config file ==="
ls -la /mnt/onboard/.adds/nm 2>&1
echo "----- contents of dashboard config: -----"
cat /mnt/onboard/.adds/nm/dashboard 2>&1
echo "------------------------------------------"
echo
echo "=== Nickel/Kobo process list ==="
ps 2>&1 | head -30
echo
echo "=== done $(date) ==="
