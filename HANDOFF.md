# Kobo Shabbos / E-Ink Reader — Project Handoff

This document is a self-contained brief for any AI or developer picking up this project. Read it top to bottom, then you should be able to extend, debug, or rebuild the system without asking the user for context.

---

## 0. ARCHITECTURE CHANGE (2026-08-25) — read this first

The dashboard approach described in §5–§6 and §9 (SIGSTOP-freezing Nickel) is **retired**. It locked the device, couldn't refresh mid-Shabbos, and needed a power-cycle to recover. Sections below remain accurate as device reference (§3, §10 hard-learned facts) and for the library (§8), but the display flow is now:

- **On-device**: the [TRMNL Kobo client](https://github.com/usetrmnl/trmnl-kobo) (v1.0.8+, field-tested on Clara HD). Started from NickelMenu, it **kills Nickel**, then loops: enable WiFi → `curl` `<TrmnlApiUrl>/display` (JSON: `image_url`, `refresh_rate`) → fetch PNG → paint via its own FBInk (WITH image support, unlike KOReader's) → disable WiFi → `rtcwake` RTC alarm → suspend to mem → wake → repeat. Exit = wake, then hold power until light blinks (reboots to Nickel).
- **Server**: none. GitHub Actions (`.github/workflows/publish-dashboard.yml`, now active) hourly publishes `dashboard.png` + a static `display` JSON to the `dashboard` branch. `TrmnlApiUrl` = `https://raw.githubusercontent.com/codepros100-dev/kobo-shabbos/dashboard`.
- **Installer**: `deploy-trmnl.ps1` (two passes: first stages Kobostuff KoboRoot.tgz for curl/jq → eject/reboot → second pass copies `.adds/TRMNL` + config + NickelMenu entry, disables the old `dashboard` menu file).
- **Config choices**: `ImageFormat: png` (native portrait 1072×1448, no rotation), `IgnoreCurlErrors: true` (failed fetch keeps last image — critical unattended over Shabbos), `LoopMaxIteration: 0`.
- **Still pending when this was written**: `gh auth refresh -s workflow` + push (token lacked `workflow` scope); first on-device test of TRMNL (watch orientation — if PNG renders rotated, see trmnl-kobo issue #17).

---

## 1. What this project is

A **Kobo Clara HD** (1072 × 1448 e-ink reader, FW 4.38, ARM Linux + Nickel UI) reconfigured to do two things:

1. **Shabbos display** — a full-screen image showing today's date (Hebrew + Gregorian), upcoming Shabbos info (parsha, candle lighting, Rabbeinu Tam, havdalah), current temp + 12-hour forecast, all in Hebrew. The image auto-refreshes when the user wants and stays on screen indefinitely.
2. **Offline Hebrew sefarim library** — 78 EPUBs sourced from [Sefaria](https://www.sefaria.org): full Tanakh (39 books), Siddur Ashkenaz, full Shas Bavli + Yerushalmi Shekalim (38 masechtos). Hebrew-only, with embedded Hebrew fonts so they render correctly on stock Kobo.

Both modes share one device: power on → library; tap a menu item → dashboard locks the screen until power-cycle.

---

## 2. The user

- Name: chaim
- Email: chaimmegadata@gmail.com
- Frum (Orthodox Jewish), wants Hebrew throughout.
- Stack: .NET / SQL / Windows. Software developer (CodePros).
- Operates on Windows 11. Repo at `C:\Users\chaim\kobo-shabbos\`.
- Kobo mounts as drive `D:` in mass-storage mode.

---

## 3. Hardware constraints (Kobo Clara HD specifics)

- **Display**: 1072 × 1448, 8-bit grayscale (`Image.new("L", ...)` in Pillow).
- **OS**: BusyBox + Qt-based "Nickel" UI, FW 4.38.23684.
- **Onboard FS**: `/mnt/onboard` is FAT32 (`/dev/mmcblk0p3`). FAT32 does not preserve `+x` bit on FAT32 mounts — workaround: scripts copy executables to `/tmp` (tmpfs) and chmod there.
- **WiFi**: aggressively powered off by Nickel; must be brought up explicitly. Only NickelMenu's `nickel_wifi:autoconnect` action reliably enables + connects without user input.
- **No `curl`** in busybox PATH for `cmd_spawn` shells — but `/usr/bin/wget` exists.
- **`fbink`** binary extracted from KOReader release zip is **compiled without image support** (`[FBInk] Image support is disabled`). Use `/usr/local/Kobo/pickel showpic` for PNG → framebuffer.
- **Custom screensaver hacks NOT installed** — once Nickel paints the home screen, anything fbink/pickel drew gets overwritten within milliseconds. The only reliable way to keep an image on screen is `killall -STOP nickel`. Recovery from that = power-cycle (long-press power 5 s, off, on).

---

## 4. Repository layout

Path: `C:\Users\chaim\kobo-shabbos\` — public repo at `https://github.com/codepros100-dev/kobo-shabbos`.

```
kobo-shabbos/
├── README.md                       # short user-facing readme
├── HANDOFF.md                      # this file
├── deploy.ps1                      # one-shot installer (downloads NickelMenu, fbink, copies scripts to D:)
├── publish-dashboard.yml.pending   # GH Actions hourly cron — NOT in .github/ because gh token lacks 'workflow' scope
│
├── generator/                      # builds the dashboard PNG
│   ├── generate_dashboard.py       # main script — Hebcal + Open-Meteo + Pillow → 1072×1448 PNG
│   ├── config.json                 # location/timezone/candle-minutes (Brooklyn defaults)
│   ├── config.example.json
│   ├── dashboard.png               # last generated output (gitignored)
│   ├── requirements.txt            # Pillow, requests, tzdata, ebooklib
│   └── fonts/
│       ├── hebrew.ttf              # Noto Sans Hebrew Regular (subset, 27KB) — Hebrew + nikud + te'amim, NO Latin
│       ├── hebrew_bold.ttf         # Noto Sans Hebrew Bold
│       ├── sans.ttf                # Noto Sans Regular (full, 569KB) — Latin+digits+symbols, NO Hebrew
│       └── sans_bold.ttf
│
├── library/                        # builds the EPUB library
│   ├── download_library.py         # Sefaria API → ebooklib → EPUB per book/masechta
│   ├── library_manifest.json       # 39 Tanakh + 1 Siddur + 38 Shas
│   ├── copy-to-kobo.ps1            # rsync-style copy from output/ to D:\Library\
│   ├── cache/                      # Sefaria API JSON cache (gitignored)
│   └── output/                     # generated EPUBs (gitignored)
│
└── kobo/bin/                       # shell scripts that live on the device at /mnt/onboard/.adds/dashboard/
    ├── update-dashboard.sh         # fetch PNG from GH dashboard branch + render via pickel/fbink
    ├── show-dashboard.sh           # update-dashboard.sh wrapper that SIGSTOPs Nickel after rendering (locks screen)
    ├── dashboard-loop.sh           # legacy hourly loop (currently unused — Nickel is killed so loops can't run)
    └── diag.sh                     # dumps device state to /mnt/onboard/.adds/dashboard/diag.log
```

### On the device (drive `D:` when in USB mass storage)

```
D:\
├── Library\
│   ├── 01 Tanakh\          # 39 EPUBs, Hebrew filenames (בראשית.epub etc.)
│   ├── 02 Siddur\          # סידור אשכנז.epub
│   └── 03 Shas Bavli\      # 38 EPUBs (incl. Yerushalmi Shekalim)
├── fonts\
│   ├── NotoSansHebrew-Regular.ttf      # for Kobo reader's font picker
│   └── NotoSansHebrew-Bold.ttf
├── .adds\
│   ├── dashboard\
│   │   ├── update-dashboard.sh
│   │   ├── show-dashboard.sh
│   │   ├── dashboard-loop.sh
│   │   ├── diag.sh
│   │   ├── fbink                    # 1.0 MB ARM ELF; lacks image support, kept as fallback
│   │   ├── dashboard.conf           # env overrides (DASHBOARD_URL, etc.)
│   │   ├── cache\
│   │   │   ├── dashboard.png        # last fetched/rendered PNG
│   │   │   ├── dashboard.log        # ALL log output goes here, append-only
│   │   │   └── loop.pid             # pid file for legacy loop (unused now)
│   │   └── diag.log                 # output of diag.sh
│   └── nm\
│       ├── dashboard                # NickelMenu config — see §6
│       └── doc                      # NickelMenu reference docs (built-in)
└── .kobo\
    └── KoboRoot.tgz                 # NickelMenu installer (consumed on boot, then deleted)
```

---

## 5. Data flow

### Dashboard refresh (single tap path)

```
User taps "Shabbos Display" in NickelMenu
   │
   ▼
NickelMenu fires nickel_wifi:autoconnect (Nickel enables + connects WiFi; non-blocking)
   │
   ▼
NickelMenu chain_always → cmd_spawn → /bin/sh /mnt/onboard/.adds/dashboard/show-dashboard.sh
   │
   ▼
show-dashboard.sh
   ├── runs update-dashboard.sh
   │      ├── waits up to 60 s for default route (`ip route | grep '^default '`)
   │      ├── tries /usr/bin/curl, /usr/local/bin/curl, curl, /usr/bin/wget,
   │      │   /usr/local/bin/wget, wget, busybox wget — first success wins
   │      ├── fetches https://raw.githubusercontent.com/codepros100-dev/kobo-shabbos/dashboard/dashboard.png
   │      ├── renders via /usr/local/Kobo/pickel showpic (then fbink fallbacks)
   │      └── exits 0 on success
   ├── waits 0 sec, then sends SIGSTOP to nickel (killall -STOP nickel)
   └── re-renders via pickel showpic so Nickel can't fight it
```

After SIGSTOP, the e-ink screen retains the PNG (e-ink is persistent). Nickel is frozen — NickelMenu, USB-Connect prompt, sleep timer all dead. Recovery = long-press power.

### Library reading

Standard Kobo flow: Nickel scans `/mnt/onboard/Library/` recursively for EPUBs, indexes via `KoboReader.sqlite`, shows in the eBooks tab. Each EPUB has:
- `dc:title` in Hebrew (e.g. `בראשית`)
- Embedded Noto Sans Hebrew via `@font-face` in `style.css` so chapter content renders even on stock firmware
- All chapters have `lang="he"` and `dir="rtl"` and reference `style.css`
- Cantillation (te'amim) and nikud included — the Sefaria source has them and the embedded font supports them

### Dashboard publishing

Currently **manual**. The hourly GH Actions cron file is at `publish-dashboard.yml.pending`. To activate, the user needs to:
```bash
gh auth refresh -s workflow
mv publish-dashboard.yml.pending .github/workflows/publish-dashboard.yml
git add . && git commit -m "enable hourly cron" && git push
```

For now, regenerate manually from a dev box:
```bash
cd generator
python generate_dashboard.py --config config.json --out dashboard.png
cd ..
git fetch origin dashboard
git worktree add -B dashboard /tmp/kdash origin/dashboard
cp generator/dashboard.png /tmp/kdash/dashboard.png
cd /tmp/kdash
git add dashboard.png
git -c user.email=chaimmegadata@gmail.com -c user.name="codepros100-dev" commit -m "refresh"
git push origin dashboard
cd - && git worktree remove /tmp/kdash
```

---

## 6. NickelMenu config (`D:\.adds\nm\dashboard`)

```ini
menu_item :main :Shabbos Display :nickel_wifi :autoconnect
  chain_always :cmd_spawn :quiet:/bin/sh /mnt/onboard/.adds/dashboard/show-dashboard.sh

menu_item :main :Run Diagnostics :nickel_wifi :autoconnect
  chain_always :cmd_spawn :quiet:/bin/sh /mnt/onboard/.adds/dashboard/diag.sh
```

Two items only. **Refresh Dashboard was removed deliberately** — it didn't suspend Nickel, so tapping it after Shabbos Display let Nickel redraw and broke the locked dashboard. The user kept tapping it accidentally.

NickelMenu syntax notes:
- `:` is the field separator. Must be `cmd_spawn :quiet:<command>` (the `:quiet:` is part of the arg, not a flag).
- `chain_always` runs the next action regardless of the previous result. `chain_success` / `chain_failure` are conditional.
- `nickel_wifi:autoconnect` is non-blocking — it tells Nickel to bring WiFi up and returns immediately. The script must wait for the default route itself.

NickelMenu doc on the device: `D:\.adds\nm\doc` (22 KB, full reference).

---

## 7. Dashboard generator (`generator/generate_dashboard.py`)

### Data sources (no API keys)
- `https://www.hebcal.com/shabbat?cfg=json&geonameid=5110302&M=on&b=18` — candle lighting, havdalah, parsha (Hebrew + English)
- `https://www.hebcal.com/zmanim?cfg=json&latitude=40.6782&longitude=-73.9442&tzid=America/New_York&date=YYYY-MM-DD` — `tzeit72min` for Rabbeinu Tam
- `https://www.hebcal.com/converter?cfg=json&gy=Y&gm=M&gd=D&g2h=1&strict=1` — Hebrew date with nikud
- `https://api.open-meteo.com/v1/forecast?latitude=...&longitude=...&current=...&hourly=...&temperature_unit=celsius` — weather

### Layout (1072 × 1448 portrait)
1. Header: weekday Hebrew (`יום שישי`), Gregorian date (`8/5/2026`), Hebrew date (`כ"א בְּאִיָּיר תשפ"ו`), city (`ברוקלין`)
2. `שבת` block: parsha Hebrew (`פרשת בהר־בחקתי`), two big boxes — `הדלקת נרות` (right) and `רבינו תם` (left), `הבדלה` time below
3. `מזג האוויר` block: current temp + Hebrew weather word, then 12-hour forecast with hour / temp / pop% / Hebrew weather, black columns for rain hours
4. Footer: last-updated timestamp

### Critical constraint: font split

The Hebrew font `hebrew.ttf` (Noto Sans Hebrew, 27 KB) has Hebrew letters + nikud + te'amim but **no Latin glyphs at all**. The Latin font `sans.ttf` (Noto Sans, 569 KB) has Latin + digits + symbols but **no Hebrew**. Pillow does not do font fallback chains.

The current generator stacks Hebrew labels above Latin values (e.g. `הבדלה` on one line, `8:46 PM` on next) instead of mixing them. Any future change that puts a digit and a Hebrew letter on the same line will render boxes for one of them. Either:
- Stack on separate lines (current approach), OR
- Find a TTF that has both (David Libre is one option; full Noto Sans Hebrew with Latin is harder to download — `https://github.com/notofonts/hebrew/raw/main/...` returned HTML; raw.githubusercontent path returned a 16 KB subset, not the full font), OR
- Implement a per-character font selector (split runs, draw with appropriate font, accumulate width).

### Hebrew labels used
| English | Hebrew |
|---|---|
| Shabbos | שבת |
| Parshas | פרשת |
| Candle Lighting | הדלקת נרות |
| Rabbeinu Tam | רבינו תם |
| Havdalah | הבדלה |
| Weather | מזג האוויר |
| Updated | עודכן (currently dropped to avoid mixing with date) |

Weather codes mapped in `WMO_HE` dict (clear/partly cloudy/rain/snow/etc.).

Weekdays: `HEB_WEEKDAY` dict, Mon=0 → `יום שני` … Sat=5 → `שבת` … Sun=6 → `יום ראשון`.

---

## 8. Library generator (`library/download_library.py`)

### Sefaria API endpoints used
- `GET /api/index/<title>` — schema metadata (used for complex schemas like Siddur)
- `GET /api/texts/<title>?context=0&pad=0&commentary=0` — bulk dump of an entire index in one HTTP call (~1-3 s per book)
- `GET /api/texts/<ref>?context=0&...` — single ref (used for complex-schema leaves)

All responses cached as JSON under `library/cache/{index,meta,ref}/`.

### Talmud labeling
Sefaria reserves array slots 0/1 for the nonexistent daf 1. Real first daf (2a) is at index 2. Formula:
```python
daf = (i // 2) + 1
side = 'a' if i % 2 == 0 else 'b'
label = f"{title} {daf}{side}"
```
Bavli has no Shekalim, so manifest substitutes `Jerusalem Talmud Shekalim` (matches the printed Vilna shas).

### Tamid quirk
Tamid starts at daf 25b. Sefaria's array still starts at index 2, so the first non-empty section in the EPUB shows up labeled `Tamid 2a` but is actually 25b text. Edge case acknowledged but not specially handled.

### Complex schemas (Siddur)
`schema_leaves(title, schema)` walks the recursive `nodes` tree and yields `(path_titles, leaf_node)` pairs. Each leaf becomes one chapter; the EPUB TOC groups them by top-level node (5 groups for Siddur Ashkenaz: Shacharit, Mincha, Maariv, Shabbat, Holidays).

### EPUB structure
Per book:
- `EPUB/content.opf` — `dc:title` is **Hebrew** (mapped via `HEBREW_TITLES` dict in the script), `dc:language=he`
- `EPUB/style.css` — `@font-face` declarations for both NotoSansHebrew Regular + Bold; body uses it; `[lang="he"]` and `[dir="rtl"]` selectors enforce direction
- `EPUB/NotoSansHebrew-Regular.ttf` + `-Bold.ttf` — embedded font files (declared `application/x-font-ttf`)
- `EPUB/about.xhtml` — Hebrew title + "About this book"
- `EPUB/sec_NNNN.xhtml` — one per chapter/section, all reference `style.css`, all `lang="he" dir="rtl"`

### Hebrew title mapping
`HEBREW_TITLES` dict in `download_library.py` covers all 78 books. Filenames also use Hebrew (e.g. `בראשית.epub` instead of `Genesis__he.epub`) — done by an ad-hoc rename step at install time, not by the generator. (TODO: bake into the generator.)

### Re-generating the library
```bash
cd library
python download_library.py all --lang he
```

If you change `HEBREW_TITLES` or the @font-face CSS, delete `library/output/` first to force a rebuild. The Sefaria API cache (`library/cache/`) doesn't need clearing — refetching from Sefaria is what's slow, and the cache is correct.

---

## 9. On-device scripts

### `update-dashboard.sh`
- Reads `dashboard.conf` for env overrides (`DASHBOARD_URL`, `CACHE_DIR`, `FBINK`, `LOG`, `WIFI_WAIT_SECONDS`).
- Copies bundled `fbink` to `/tmp/fbink-dashboard` once (FAT32 strips +x bit; tmpfs preserves it).
- Waits up to 60 s for `ip route | grep '^default '` to succeed.
- `fetch()` tries every common downloader path. Stock Kobo busybox sh has no `curl` on PATH; `/usr/bin/wget` exists.
- Renders with `/usr/local/Kobo/pickel showpic` first (proven to work), then bundled fbink (fails — no image support), then system fbink (not present).
- Exit codes: 0 ok, 1 fetch failed, 2 render failed.
- Every step writes to `$LOG` with a timestamp.

### `show-dashboard.sh`
- Calls `update-dashboard.sh`. Aborts only on `rc=1` (no cached image AND fetch failed).
- `killall -STOP nickel` (or `kill -STOP $(pidof nickel)` fallback) to freeze the screen.
- Re-renders via pickel showpic so Nickel can't have redrawn during the SIGSTOP race.
- Final state: dashboard PNG painted, Nickel suspended, screen will retain image until power-cycle.

### `diag.sh`
- Dumps to `/mnt/onboard/.adds/dashboard/diag.log`:
  - `id`, `pwd`, `PATH`, `uname`
  - `mount` (top 20)
  - directory listing of `/mnt/onboard/.adds/dashboard`
  - `file fbink` + executability check + `fbink -v`
  - `/usr/local/Kobo` listing
  - `/usr/local/Kobo/pickel` size
  - `which curl`, `curl -V`
  - `ip addr`, `ip route`
  - reachability test to `https://raw.githubusercontent.com/codepros100-dev/kobo-shabbos/dashboard/dashboard.png`
  - `libnm.so` presence (NickelMenu loaded check)
  - NickelMenu config dump
  - `ps` listing

### `dashboard-loop.sh` (LEGACY)
A long-running loop that refreshes hourly, single-instance via PID file, listens for STOP file. **Not currently used** — when Nickel is suspended, no spawned shell can survive predictably, and there's no cron. Kept for future use if the screensaver-mod approach becomes viable.

---

## 10. Critical "things we already learned the hard way"

1. **`curl` is not in busybox PATH on Kobo.** Use `/usr/bin/wget` or `busybox wget` with `--no-check-certificate`.
2. **The bundled `fbink` from KOReader has image support disabled** (`[FBInk] Image support is disabled in this FBInk build!`). Use `pickel showpic` for PNG rendering.
3. **Nickel redraws over fbink/pickel within milliseconds.** Without `killall -STOP nickel`, the dashboard image is invisible to the user. There is no clean way to keep an image on screen while Nickel runs (without installing a custom screensaver mod).
4. **WiFi is off by default and Nickel won't bring it up unless asked.** Use `nickel_wifi:autoconnect` from NickelMenu.
5. **NickelMenu `cmd_spawn` runs in busybox sh with limited PATH.** Use absolute paths for everything.
6. **FAT32 doesn't preserve +x bit.** Copy executables to `/tmp` first.
7. **Sefaria's complex schemas (Siddur) return HTTP 400 for the bulk endpoint.** Use `/api/index/<title>` to get the schema, walk it, then fetch each leaf with `/api/texts/<ref>`.
8. **Talmud array indexing is off-by-2** (slots 0/1 reserved for nonexistent daf 1). `daf = (i//2) + 1`.
9. **CRLF line endings break busybox sh.** Always normalize `.sh` and NickelMenu config files to LF when writing from Windows. Quick check: `python -c "d=open(p,'rb').read(); open(p,'wb').write(d.replace(b'\r\n', b'\n'))"`.
10. **The Hebrew font we ship has no Latin glyphs.** Don't put `2026` and `יום שישי` on the same line — one of them will render as boxes.
11. **gh auth token lacks `workflow` scope.** Can't push files to `.github/workflows/` from this machine without `gh auth refresh -s workflow`.
12. **The Kobo can't go into USB mass-storage mode if Nickel is suspended.** The "Connect to PC" prompt is rendered by Nickel — if it's frozen, no prompt. User must power-cycle first.

---

## 11. Setup / install (from scratch on a fresh Kobo)

1. On Kobo: factory reset, complete WiFi setup with the user's home network so credentials are saved.
2. Plug Kobo into Windows machine, tap **Connect** on the Kobo.
3. From the repo root:
   ```powershell
   .\deploy.ps1
   ```
   This script:
   - Auto-detects the Kobo drive letter (`KOBOeReader`).
   - Downloads NickelMenu KoboRoot.tgz from `pgaskin/NickelMenu` GitHub releases v0.6.0, drops it at `D:\.kobo\KoboRoot.tgz`.
   - Extracts `koreader/fbink` from the latest KOReader release zip in `_downloads/`, drops at `D:\.adds\dashboard\fbink`.
   - Copies all `kobo/bin/*.sh` to `D:\.adds\dashboard\` with LF endings.
   - Writes `D:\.adds\dashboard\dashboard.conf` from defaults.
   - Writes `D:\.adds\nm\dashboard` (NickelMenu config — see §6).
   - Copies `library/output/{tanakh,siddur,shas_bavli}/*__he.epub` to `D:\Library\` with Hebrew filenames.
   - Drops `generator/fonts/hebrew*.ttf` into `D:\fonts\` for the reader's font picker.
4. Eject the drive. Kobo will boot, consume `KoboRoot.tgz` (installs NickelMenu), reboot, scan content (~3-5 min for 78 EPUBs).
5. From home screen → NickelMenu → **Shabbos Display**. First run takes ~30 s for WiFi connect + fetch + render.

---

## 12. Open issues / future work

- **GitHub Actions hourly publish**: workflow file pending at `publish-dashboard.yml.pending`, blocked on `gh auth refresh -s workflow`. Once enabled, the dashboard branch updates every hour and the device fetches fresh data on each Shabbos Display tap.
- **No mid-day auto-refresh on device**: because the dashboard mode kills Nickel, no scheduler can run. User must power-cycle and re-tap to refresh. Could be solved with a custom screensaver mod (NiLuJe's CSPSH) that lets Nickel keep running while the lock-screen image shows our PNG.
- **Hebrew filename rename is ad-hoc**: done by a Python snippet at install time, not by `download_library.py`. Bake it into the generator.
- **Mixed Hebrew/Latin still rendered as separate stacked lines**: future cleaner solution would be a per-character-script font selector in the dashboard generator.
- **`update-dashboard.sh` log can grow forever**: no rotation. Add a `tail -1000 > $LOG.tmp && mv $LOG.tmp $LOG` step on each invocation.
- **Tamid daf labeling**: starts at index 2 = "Tamid 2a" but is actually 25b. Cosmetic.
- **Dashboard timezone is hardcoded** to America/New_York in `config.json`. For a non-Brooklyn user, edit `config.json`.
- **No alarm / notification for candle-lighting time**. Could be added as a fbink-text-overlay close to the candle time, but Nickel-suspend trade-offs apply.

---

## 13. Useful commands

### Inspect device state without unmounting
```powershell
Get-Content 'D:\.adds\dashboard\cache\dashboard.log' -Tail 60
Get-Content 'D:\.adds\dashboard\diag.log'
Get-ChildItem 'D:\Library' -Recurse | Measure-Object
```

### Regenerate one EPUB and inspect
```bash
cd library
python download_library.py one Berakhot --lang he
cd /tmp && rm -rf inspect && mkdir inspect && cd inspect
unzip -q /c/Users/chaim/kobo-shabbos/library/output/custom/Berakhot__he.epub
cat EPUB/content.opf | head -20
cat EPUB/style.css
ls -la EPUB/NotoSansHebrew-*.ttf
```

### Push fresh dashboard PNG to GitHub
See §5 "Dashboard publishing" above.

### Verify Hebrew title in EPUB metadata
```bash
unzip -p D:/Library/01\ Tanakh/בראשית.epub EPUB/content.opf | grep -E 'dc:title|dc:lang'
```

### Test fonts cover required Unicode ranges
```python
from fontTools.ttLib import TTFont
t = TTFont('generator/fonts/hebrew.ttf', lazy=True)
cmap = t['cmap'].getBestCmap()
# Hebrew aleph U+05D0, kamatz U+05B8, etnachta U+0591
print(0x05D0 in cmap, 0x05B8 in cmap, 0x0591 in cmap)
```

---

## 14. Glossary (for an AI unfamiliar with the domain)

- **Shabbos** — Sabbath, Friday sundown to Saturday nightfall. Begins ~18 min before sunset (`candle lighting`), ends with `havdalah` after 3 stars or `Rabbeinu Tam` (72 min after sunset, stricter).
- **Parsha / Parashat** — weekly Torah portion. The current week's parsha is what's read in shul on Shabbos morning. Hebcal returns it as `parashat` items in the Shabbat API.
- **Zmanim** — halachic times of day (sunrise, sunset, etc.). Hebcal's zmanim API returns dozens; we use only `tzeit72min` (Rabbeinu Tam time).
- **Hebrew date** — lunisolar calendar (e.g. `כ״א בְּאִיָּיר תשפ"ו` = 21 Iyyar 5786). Display includes nikud (vowel marks) for clarity.
- **Sefer / Sefarim** — Hebrew "book / books"; here means religious texts.
- **Tanakh** — Hebrew Bible (Torah + Nevi'im + Ketuvim). 39 books in our manifest matching standard Jewish division.
- **Shas / Talmud** — 60+ tractates (`masechtos`) of rabbinic law. Bavli = Babylonian (primary). Yerushalmi = Jerusalem Talmud. We include 37 Bavli + Yerushalmi Shekalim (Bavli has no Shekalim).
- **Daf / Amud** — page of Talmud, two amudim (a/b) per daf.
- **Siddur** — prayer book. We include the Ashkenazi nusach (rite).
- **Nikud** — Hebrew vowel marks (dots and dashes under/above letters). Optional in modern Hebrew, standard in liturgy and Tanakh.
- **Te'amim** — cantillation marks for Tanakh chant. The Sefaria source includes them.

---

## 15. How to ask the user good questions

The user is not a Linux internals expert and gets frustrated when asked the same thing twice. Helpful patterns:
- **Say what you see, then propose ONE next action.** Not three options.
- **If a fix needs the device unplugged-replugged, say it once, with the reason.** Don't repeat the procedure unless asked.
- **Always check D: is mounted before promising to push files.** Use `Test-Path 'D:\'` first.
- **Read the log before guessing.** `D:\.adds\dashboard\cache\dashboard.log` and `D:\.adds\dashboard\diag.log` are authoritative.
- **The user prefers Hebrew over English in user-facing output.** When in doubt, use Hebrew.
