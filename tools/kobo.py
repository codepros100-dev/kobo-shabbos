"""
Talk to the Kobo over Wi-Fi (needs Kobostuff's passwordless telnet/FTP on the device).

    python tools/kobo.py find                 # scan the LAN for the Kobo
    python tools/kobo.py run "tail -20 /mnt/onboard/.adds/shabbos/log.txt"
    python tools/kobo.py get .adds/shabbos/log.txt log.txt
    python tools/kobo.py put device/shabbos/shabbos.sh .adds/shabbos/shabbos.sh
    python tools/kobo.py shot shot.png        # screenshot of the e-ink screen

The address is cached in tools/.kobo-ip; pass --ip to override.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import ftplib
import re
import socket
import sys
import time
from pathlib import Path

IP_FILE = Path(__file__).parent / ".kobo-ip"
MARK = "__KOBO_DONE__"


def local_prefixes() -> list[str]:
    out = set()
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        ip = info[4][0]
        if not ip.startswith(("127.", "169.254.")):
            out.add(ip.rsplit(".", 1)[0])
    return sorted(out)


def port_open(ip: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def find() -> str | None:
    for prefix in local_prefixes():
        ips = [f"{prefix}.{i}" for i in range(1, 255)]
        with concurrent.futures.ThreadPoolExecutor(64) as pool:
            hits = [ip for ip, ok in zip(ips, pool.map(lambda a: port_open(a, 23), ips)) if ok]
        for ip in hits:
            try:
                if "Kobo" in run(ip, "cat /mnt/onboard/.kobo/version; echo Kobo-check", 8):
                    IP_FILE.write_text(ip)
                    return ip
            except OSError:
                continue
    return None


def run(ip: str, cmd: str, timeout: float = 60) -> str:
    """Run a shell command over telnet and return its output."""
    with socket.create_connection((ip, 23), timeout=10) as s:
        s.settimeout(2)
        buf = b""
        deadline = time.time() + 5
        while time.time() < deadline and not buf.rstrip().endswith((b"#", b"$")):
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            # Refuse every telnet option the server offers.
            for m in re.finditer(rb"\xff([\xfb-\xfe])(.)", chunk):
                reply = b"\xfe" if m.group(1) in (b"\xfb", b"\xfc") else b"\xfc"
                s.sendall(b"\xff" + reply + m.group(2))
            buf += re.sub(rb"\xff[\xfb-\xfe].", b"", chunk)
        s.sendall(f"stty -echo 2>/dev/null; {cmd}; echo {MARK}$?\n".encode())
        out = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                break
            out += chunk
            if re.search(MARK.encode() + rb"\d+", out):
                break
    text = out.decode("utf-8", "replace").replace("\r", "")
    text = text.split(f"echo {MARK}$?\n", 1)[-1]
    return re.sub(MARK + r"(\d+)\s*.*$", r"[exit \1]", text, flags=re.S)


def ftp(ip: str) -> ftplib.FTP:
    f = ftplib.FTP()
    f.connect(ip, 21, timeout=20)
    f.login("root", "")
    return f


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip")
    ap.add_argument("command", choices=["find", "run", "get", "put", "shot"])
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()

    if a.command == "find":
        ip = find()
        print(ip or "Kobo not found (is Wi-Fi on and connected?)")
        return 0 if ip else 1

    ip = a.ip or (IP_FILE.read_text().strip() if IP_FILE.exists() else None) or find()
    if not ip:
        print("Kobo not found", file=sys.stderr)
        return 1

    if a.command == "run":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(run(ip, " ".join(a.args)))
    elif a.command == "get":
        with ftp(ip) as f, open(a.args[1], "wb") as fh:
            f.retrbinary(f"RETR {a.args[0]}", fh.write)
    elif a.command == "put":
        with ftp(ip) as f, open(a.args[0], "rb") as fh:
            f.storbinary(f"STOR {a.args[1]}", fh)
    elif a.command == "shot":
        print(run(ip, "fbgrab /mnt/onboard/.adds/shot.png >/dev/null 2>&1; ls -la /mnt/onboard/.adds/shot.png"))
        with ftp(ip) as f, open(a.args[0], "wb") as fh:
            f.retrbinary("RETR .adds/shot.png", fh.write)
    return 0


if __name__ == "__main__":
    sys.exit(main())
