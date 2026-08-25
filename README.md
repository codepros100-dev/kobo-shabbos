# Kobo Clara HD — Shabbos Dashboard + Offline Jewish Library

Turn a Kobo Clara HD into a self-updating Shabbos / zmanim / weather display
**and** a fully offline Sefaria-backed Hebrew library (Tanakh, Siddur, full Shas).

## How the dashboard works (v2 — TRMNL client)

The old approach (shell loop under Nickel, then SIGSTOP-freezing Nickel) fought
the firmware and lost: Nickel either put the device to sleep and painted its
screensaver over the dashboard, or the frozen device needed a power-cycle.

v2 uses the [TRMNL Kobo client](https://github.com/usetrmnl/trmnl-kobo)
(field-tested on the Clara HD) with **no server** — GitHub serves everything:

1. A GitHub Actions cron re-renders `dashboard.png` hourly from Hebcal
   (zmanim, parsha, Hebrew date) and Open-Meteo (weather), and publishes it
   plus a static TRMNL `display` JSON to the orphan `dashboard` branch.
2. On the Kobo, tapping **Shabbos Display** (NickelMenu) starts the TRMNL
   client. It stops Nickel, then loops forever:
   **enable WiFi → fetch JSON + PNG → paint with fbink → disable WiFi →
   suspend with an RTC wake alarm → wake after an hour → repeat.**
3. E-ink keeps the image with zero power while suspended, so the dashboard
   stays visible around the clock, updates itself hourly, and never needs to
   be touched — battery lasts weeks.

Exiting after Shabbos: press power once to wake it, then **hold** power until
the light blinks rapidly; release. The device reboots back into Nickel
(library/reading mode).

## What this repo gives you

| Piece | What it does | Where it runs |
| --- | --- | --- |
| `generator/generate_dashboard.py` | Renders a 1072×1448 Hebrew PNG dashboard from Hebcal + Open-Meteo | Locally OR in CI |
| `.github/workflows/publish-dashboard.yml` | Regenerates the PNG hourly and publishes it + the TRMNL `display` JSON to the `dashboard` branch | GitHub Actions (free) |
| `deploy-trmnl.ps1` | Installs the TRMNL client + Kobostuff on the Kobo, pointed at this repo (BYOS) | Your Windows PC |
| `deploy.ps1` | Legacy installer (NickelMenu + old shell scripts + library) | Your Windows PC |
| `library/download_library.py` | Builds per-masechta / per-sefer Hebrew EPUBs from Sefaria's API | Locally |
| `library/copy-to-kobo.ps1` | Pushes the EPUBs onto the Kobo | Your Windows PC |

## Setup — dashboard

1. **Enable the hourly workflow** (one-time). The repo's `gh` token needs the
   `workflow` scope:

   ```bash
   gh auth refresh -s workflow
   ```

   Then commit and push `.github/workflows/publish-dashboard.yml`. The Action
   runs hourly and on every push; the first PNG + `display` JSON appear on the
   `dashboard` branch within ~2 minutes.

2. **Install on the Kobo.** Plug it in, tap Connect, then:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\deploy-trmnl.ps1
   ```

   The first run stages Kobostuff (`curl` + `jq` for the client) — eject, let
   the Kobo reboot, reconnect, and **run the script again** to finish.
   (NickelMenu must already be installed — it is, via the original `deploy.ps1`.)

3. **Start it.** On the Kobo: NickelMenu → **Shabbos Display**. First paint
   takes ~30 s (WiFi + fetch). After that it's fully hands-off.

## Setup — Library (one-time, ~45 min)

```powershell
cd library
py -m pip install -r ..\generator\requirements.txt
py download_library.py all --lang he
powershell -ExecutionPolicy Bypass -File .\copy-to-kobo.ps1
```

Builds Tanakh (39 books), Siddur Ashkenaz, and full Shas Bavli (+ Yerushalmi
Shekalim) as Hebrew EPUBs with embedded Noto Sans Hebrew, landing in
`Library/01 Tanakh`, `02 Siddur`, `03 Shas Bavli` on the device. Resumable —
sections are cached under `library/cache/`.

## Day-to-day

- **Dashboard mode** (Shabbos): tap Shabbos Display once; it self-updates
  hourly until you exit via the power-button sequence.
- **Reading mode**: normal Kobo. The library is fully offline.
- To change the dashboard layout, edit `generator/generate_dashboard.py` and
  push — CI regenerates within ~2 minutes; the Kobo picks it up on its next
  hourly wake.

## Troubleshooting

- Client log while plugged in: `<KOBO>\.adds\TRMNL\debug.log` (copied from
  `/tmp/debug.log` on exit).
- Connection errors on wake → raise `ConnectedGracePeriod` in
  `<KOBO>\.adds\TRMNL\config.json`.
- With `IgnoreCurlErrors: true` (our default) a failed fetch keeps showing the
  last good image instead of an error screen.
- Deep device details and hard-learned Kobo quirks: see `HANDOFF.md`.

## Licensing notes

- Dashboard data: Hebcal API (free, attribution requested), Open-Meteo (CC-BY 4.0).
- Hebrew text: classical editions, public domain.
- Fonts: Noto Sans / Noto Sans Hebrew, SIL OFL.
- TRMNL client, NickelMenu, Kobostuff, FBInk: see their upstream licenses.
- Code: do whatever you want with it.
