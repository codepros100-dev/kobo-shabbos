# Kobo Shabbos — project brief (v3, 2026-11-12)

A Kobo Clara HD (N249, 1072×1448, firmware 4.38+) used for two things:

1. **Shabbos display** — full-screen Hebrew page: day, Hebrew date, parsha / Yom Tov,
   candle lighting, havdalah, Rabbeinu Tam, plus weather (live) or the day's zmanim (offline).
2. **Sefarim** — Tanakh, Siddur Ashkenaz and Shas in Hebrew, read in KOReader.

User: frum, Lakewood NJ, Windows 11, .NET developer, not a Linux person. Prefers Hebrew in
anything user-facing, short answers, one proposed action at a time.

## Why v1 and v2 failed (do not repeat)

- v1 froze Nickel with SIGSTOP: no refresh, power-cycle to recover.
- v2 (TRMNL client) never ran once: NickelMenu starts scripts with `cwd=/` and a minimal
  `PATH`, and `trmnl.sh` read `config.json` and called `jq`/`curl` by relative name.
  Separately, the GitHub Actions workflow was never pushed (token lacked `workflow` scope),
  so the published image was months stale. Nothing was ever tested on the device.
- Hebrew books looked bad because the stock reader's EPUB engine does not position
  nikud/te'amim (no OpenType mark positioning) and the books embedded a sans font subset.

## Design (v3)

**Offline-first.** The device carries one pre-rendered page per day (`pages/YYYY-MM-DD.png`,
400 days). Each cycle it tries to fetch the live page (with weather) from GitHub; if that
fails or the page is stale it shows today's offline page. It can never be blank or wrong
because of Wi-Fi, GitHub or the PC.

```
generator/generate_dashboard.py   live  -> dashboard.png + dashboard.txt (epoch stamp)
                                  pack  -> build/pages/YYYY-MM-DD.png
.github/workflows/publish-dashboard.yml   hourly `live` -> force-push to `dashboard` branch
device/shabbos/shabbos.sh         on-device loop (absolute paths everywhere)
device/nm/shabbos                 NickelMenu entries: "Shabbos Display", "Sefarim"
device/koreader/settings.reader.lua   first-run KOReader defaults (Hebrew UI, font, kerning)
library/download_library.py       Sefaria -> Hebrew EPUBs (cache in library/cache/)
deploy.ps1                        installs all of it onto the Kobo over USB
```

### On-device loop (`/mnt/onboard/.adds/shabbos/shabbos.sh`)

Started from NickelMenu. Detaches (setsid), kills Nickel, then forever:
Wi-Fi up → fetch `dashboard.txt` (reject if older than 3 h) + `dashboard.png` → else today's
offline page → paint with FBInk if changed → Wi-Fi down → RTC-alarm suspend until the next
`:25` or just after midnight. **Exit: press the power button once** (reboots into Nickel).
Log: `.adds/shabbos/log.txt`. Settings can be overridden in `.adds/shabbos/config`
(shell syntax: `URL_BASE`, `TZ`, `MAX_AGE`, `SLOT_MINUTE`, `KEEP_AWAKE`).
A file named `.adds/shabbos/DEBUG` (or `deploy.ps1 -KeepAwake`) keeps it awake with Wi-Fi on.

While the display runs, Nickel is gone, so USB "Connect" does not appear — exit first.

### Reader

KOReader in `.adds/koreader`, books in `.adds/sefarim` (dot-folder so the stock reader does
not import them and show them badly). Fonts in `.adds/koreader/fonts/hebrew`:
Taamey Frank CLM (default; nikud + te'amim), Ezra SIL, Frank Ruhl Libre.
Font kerning must stay on "best" (HarfBuzz) or marks are misplaced.

### Getting a shell (for debugging)

Kobostuff (NiLuJe) is installed: when Wi-Fi is up the Kobo serves passwordless
telnet (23), FTP (21, root = /mnt/onboard) and SSH (22) on the LAN. Home network only.
Screenshot: `fbgrab /mnt/onboard/shot.png`, then fetch by FTP.

## Routine tasks

- New offline pages (yearly, or after changing location): `python generator/generate_dashboard.py pack --out-dir build/pages --days 400` then `.\deploy.ps1 -Skip koreader,library`.
- Rebuild books: `python library/download_library.py all` then `.\deploy.ps1 -Skip koreader,display`.
- Location/timezone: `generator/config.json` (and `TZ` in `shabbos.sh` if not US Eastern).

## Facts learned the hard way

- NickelMenu `cmd_spawn`: `cwd=/`, minimal PATH. Absolute paths only.
- Shell scripts and NickelMenu files must be LF. `deploy.ps1` normalises.
- Hebcal's converter returns a different JSON shape for a one-day range; always ask for 2+.
- Sefaria Talmud arrays reserve slots 0/1; daf = i // 2 + 1.
- Sefaria text contains HTML entities and unclosed tags; run it through lxml before XHTML.
- Pushing `.github/workflows/*` needs a token with the `workflow` scope.

## Status

Verified on the device 2026-11-12 (firmware 4.38.23852), via telnet + screenshots:
- Display starts from NickelMenu, paints the offline page upright, power button exits.
- Wi-Fi down → RTC suspend (150 s) → wake → Wi-Fi up, two clean cycles. The first suspend
  after start was refused by the kernel; a 3-try retry was added afterwards and that retry
  has **not** been exercised on the device yet.
- KOReader opens Bereishis in Taamey Frank CLM with nikud and te'amim placed correctly.

- Workflow pushed; the push-triggered run published a correct live page (Hebrew shaped
  properly on the Linux runner).

Not verified: page-turn direction in KOReader (Hebrew UI, no `inverse_reading_order` set),
the device actually fetching the live page (it was only tested before anything was
published), the hourly schedule firing, battery life over a full Shabbos.

Test hooks in `.adds/shabbos/config`: `NAP_OVERRIDE=150`, `MAX_CYCLES=3`.
