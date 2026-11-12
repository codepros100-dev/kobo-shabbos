# Kobo Shabbos

A Kobo Clara HD as a Hebrew **Shabbos display** and an offline **sefarim** reader.

- **Shabbos Display** (NickelMenu → *Shabbos Display*): day, Hebrew date, parsha / Yom Tov,
  candle lighting, havdalah, Rabbeinu Tam, weather. Refreshes hourly by itself. Works with no
  Wi-Fi too: the device carries a page for every day of the next 400 days and shows that
  whenever it can't get the live one. **To leave: press the power button once.**
- **Sefarim** (NickelMenu → *Sefarim*): Tanakh, Siddur, Shas in KOReader, which renders
  nikud and te'amim correctly.

## Install / update

Plug the Kobo in, tap **Connect**, then:

```powershell
.\deploy.ps1
```

Requires NickelMenu on the device. See [HANDOFF.md](HANDOFF.md) for the design, the
on-device layout, debugging over Wi-Fi (`tools/kobo.py`) and routine tasks.
