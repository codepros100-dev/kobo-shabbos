# Kobo Clara HD — Shabbos Dashboard + Offline Jewish Library

Turn a Kobo Clara HD into a self-updating Shabbos / zmanim / weather display
**and** a fully offline Sefaria-backed library (Tanakh, Siddur, full Shas).

## What this repo gives you

| Piece | What it does | Where it runs |
| --- | --- | --- |
| `generator/generate_dashboard.py` | Renders a 1072×1448 PNG dashboard from Hebcal + Open-Meteo | Locally OR in CI |
| `.github/workflows/publish-dashboard.yml` | Re-generates the PNG hourly, force-pushes it to a `dashboard` branch | GitHub Actions (free) |
| `kobo/bin/dashboard-loop.sh` + `update-dashboard.sh` | Pulls the PNG over WiFi and paints it to the e-ink screen | On the Kobo |
| `kobo/install/install-on-kobo.ps1` | Copies scripts to the Kobo over USB | Your Windows PC |
| `library/download_library.py` | Builds per-masechta / per-sefer EPUBs from Sefaria's API | Locally |
| `library/copy-to-kobo.ps1` | Pushes the EPUBs onto the Kobo | Your Windows PC |

## Architecture in one paragraph

A free GitHub Actions cron job re-renders the dashboard PNG every hour using
Hebcal (zmanim, parsha, Hebrew date) and Open-Meteo (weather), and force-pushes
it to an orphan `dashboard` branch in this repo so it has a stable raw URL.
On the Kobo, **KFMon** watches a "Dashboard" book in your library; tapping it
launches a small shell loop that uses `curl` to pull that PNG and `fbink` to
paint it directly to the e-ink framebuffer. Nickel keeps running in the
background and manages WiFi, so you don't need to replace the OS.

## Setup — one-time

There are five steps. Three are on the Kobo and two are on your PC.

### 1. Push this repo to GitHub

```powershell
cd C:\Users\chaim\kobo-shabbos
git init
git add .
git commit -m "Initial Kobo Shabbos dashboard"
gh repo create kobo-shabbos --private --source . --push
```

Then in **`generator/config.json`**, set your latitude/longitude/timezone (the
example is Brooklyn, NY). Commit and push. The Action runs hourly on cron and
also on every push, so the first PNG appears within ~2 minutes.

The published URL is:

```
https://raw.githubusercontent.com/<your-user>/kobo-shabbos/dashboard/dashboard.png
```

### 2. Install everything on the Kobo (~1 min, one eject)

The deploy script does it all: drops NickelMenu's `KoboRoot.tgz` in `.kobo/`,
extracts an `fbink` binary from the latest KOReader release, copies our
shell scripts + a NickelMenu config + the EPUB library to the device.

```powershell
cd C:\Users\chaim\kobo-shabbos
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

When it finishes, **safely eject the Kobo from Windows.** On disconnect the
device shows "Updating…" for ~30 s, reboots, and NickelMenu is installed.

### 3. Configure WiFi on the Kobo

In Nickel: **Settings → Wireless connection** → join your home network.

### 4. Start the dashboard

Open Nickel's hamburger menu (top-left of home, or the tabs row on newer
firmware). You'll see three new entries:

- **Shabbos Dashboard** — starts the long-running loop (one tap per reboot).
- **Refresh Dashboard** — force-refresh now.
- **Stop Dashboard** — kill the loop cleanly.

Tap **Shabbos Dashboard**. The e-ink screen repaints with the live PNG within
about 5 seconds. The loop refreshes once an hour automatically.

> The loop ends when the Kobo reboots; tap **Shabbos Dashboard** again to
> restart. True boot autostart would require patching `/etc/init.d/rcS`,
> which we don't do — Kobo firmware updates would clobber it.

---

## Setup — Library (one-time, ~45 min)

```powershell
cd C:\Users\chaim\kobo-shabbos\library
py -m pip install -r ..\generator\requirements.txt
py download_library.py all --lang both
```

This builds:

- **Tanakh** (39 books, includes Tehillim) → `output/tanakh/*.epub`
- **Siddur Ashkenaz** → `output/siddur/*.epub`
- **Full Shas Bavli** (37 Bavli masechtot + Yerushalmi Shekalim — matches printed Vilna Shas) → `output/shas_bavli/*.epub`

The script is **resumable** — every section is cached under `library/cache/`,
so if it dies halfway you can re-run and it picks up where it left off.

Then push to the Kobo:

```powershell
powershell -ExecutionPolicy Bypass -File .\copy-to-kobo.ps1
```

Files land in `Library/01 Tanakh/`, `Library/02 Siddur/`, `Library/03 Shas Bavli/`
on the device, organized for browsing.

---

## Day-to-day

- **Dashboard updates by itself** as long as the Kobo has WiFi.
- **Library is offline.** No internet needed once EPUBs are on the device.
- To customize the dashboard, edit `generator/generate_dashboard.py` and push.
  The Action regenerates within ~2 minutes; the Kobo picks it up at the next
  refresh (hourly by default — set `REFRESH_SECONDS` in `dashboard.conf` to
  pull more often).
- To regenerate the library after Sefaria text updates, just re-run
  `download_library.py`. It only re-fetches sections newer than the cache.

## Local testing

To preview the dashboard PNG without involving GitHub or the Kobo:

```powershell
cd C:\Users\chaim\kobo-shabbos\generator
py -m pip install -r requirements.txt
copy config.example.json config.json   # edit for your location
py generate_dashboard.py --config config.json --out dashboard.png
start dashboard.png
```

## Logs and troubleshooting

While the Kobo is plugged in, its log is visible from your PC at:

```
<KOBO_DRIVE>\.adds\dashboard\cache\dashboard.log
```

Useful greps:

```powershell
type F:\.adds\dashboard\cache\dashboard.log | Select-Object -Last 30
```

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Tap `Dashboard`, nothing happens | KFMon didn't pick up our `.ini` | Re-eject; verify `.adds\kfmon\config\dashboard.ini` exists on the device |
| Log says `fetch failed` | WiFi not up yet | Wait, or open the Kobo's web browser once to force-connect |
| Log says `fbink: not found` | KFMon's bundled fbink is missing | Reinstall KFMon's `KoboRoot.tgz` (latest release ships with fbink) |
| Dashboard image looks blurry | PNG is being scaled | Check `display.width`/`height` in `generator/config.json` matches Clara HD (1072×1448) |

## Licensing notes

- Dashboard data: Hebcal API (free, attribution requested),
  Open-Meteo (CC-BY 4.0).
- Hebrew text: classical editions, public domain.
- English Talmud: William Davidson Talmud, **CC-BY-NC** — fine for personal
  use. Don't redistribute the EPUBs commercially.
- Fonts: Noto Sans / Noto Sans Hebrew, SIL OFL.
- Code: do whatever you want with it.
