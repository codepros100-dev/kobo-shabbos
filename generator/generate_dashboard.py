"""
Shabbos display pages for the Kobo Clara HD (1072x1448, 8-bit grayscale).

Two outputs from one layout:

  live   one PNG for "now", with weather. Published hourly by GitHub Actions.
  pack   one PNG per calendar day (no weather, daily zmanim instead), copied
         onto the device. The device shows the page for today's date whenever
         it cannot get a fresh live image, so it is never blank or stale.

Data (free, no API key): Hebcal (events, zmanim, Hebrew dates), Open-Meteo.

Usage:
    python generate_dashboard.py live --out dashboard.png --stamp dashboard.txt
    python generate_dashboard.py pack --out-dir pages --days 400
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont, features

HEBCAL_EVENTS = "https://www.hebcal.com/hebcal"
HEBCAL_ZMANIM = "https://www.hebcal.com/zmanim"
HEBCAL_CONVERT = "https://www.hebcal.com/converter"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

# One font with both Hebrew and Latin glyphs, so mixed lines just work.
FONT_PATH = Path(__file__).parent / "fonts" / "Heebo.ttf"
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/heebo/Heebo%5Bwght%5D.ttf"

WMO_HE = {
    0: "בהיר", 1: "בהיר", 2: "מעונן חלקית", 3: "מעונן",
    45: "ערפל", 48: "ערפל",
    51: "טפטוף", 53: "טפטוף", 55: "טפטוף",
    56: "טפטוף קופא", 57: "טפטוף קופא",
    61: "גשם קל", 63: "גשם", 65: "גשם כבד",
    66: "גשם קופא", 67: "גשם קופא",
    71: "שלג קל", 73: "שלג", 75: "שלג כבד", 77: "שלג",
    80: "ממטרים", 81: "ממטרים", 82: "ממטרים",
    85: "שלג", 86: "שלג כבד",
    95: "רעמים", 96: "ברד", 99: "ברד",
}
WET_CODES = set(range(51, 68)) | set(range(80, 83)) | {95, 96, 99}

# Mon=0 .. Sun=6
HEB_WEEKDAY = ["יום שני", "יום שלישי", "יום רביעי", "יום חמישי",
               "יום שישי", "יום שבת", "יום ראשון"]

# (label, hebcal zmanim key) shown on offline pages, in reading order.
ZMANIM_ROWS = [
    ("עלות השחר", "alotHaShachar"),
    ("נץ החמה", "sunrise"),
    ("סוף זמן ק״ש מג״א", "sofZmanShmaMGA"),
    ("סוף זמן ק״ש גר״א", "sofZmanShma"),
    ("סוף זמן תפילה", "sofZmanTfilla"),
    ("חצות", "chatzot"),
    ("מנחה גדולה", "minchaGedola"),
    ("פלג המנחה", "plagHaMincha"),
    ("שקיעה", "sunset"),
    ("צאת הכוכבים", "tzeit7083deg"),
]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, timeout=45)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 - retry anything transient
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def chunks(start: dt.date, end: dt.date, days: int):
    cur = start
    while cur <= end:
        nxt = min(cur + dt.timedelta(days=days - 1), end)
        yield cur, nxt
        cur = nxt + dt.timedelta(days=1)


def loc_params(loc: dict[str, Any]) -> dict[str, Any]:
    if loc.get("geonameid"):
        return {"geonameid": loc["geonameid"]}
    return {"latitude": loc["latitude"], "longitude": loc["longitude"],
            "tzid": loc["timezone"]}


# ---------------------------------------------------------------------------
# Calendar data for a date range
# ---------------------------------------------------------------------------
class Calendar:
    """Events, zmanim and Hebrew dates for [start, end], fetched in bulk."""

    def __init__(self, loc: dict[str, Any], start: dt.date, end: dt.date):
        self.tz = ZoneInfo(loc["timezone"])
        self.candles: list[dt.datetime] = []
        self.havdalah: list[dt.datetime] = []
        self.parsha: dict[dt.date, str] = {}
        self.holidays: dict[dt.date, list[tuple[str, bool]]] = {}
        self.zmanim: dict[str, dict[str, str]] = {}
        self.hdates: dict[str, dict[str, Any]] = {}

        # Events need a margin: a page looks ahead to the next candle lighting
        # and its havdalah (up to 3 days later on a long Yom Tov).
        ev_start, ev_end = start - dt.timedelta(days=4), end + dt.timedelta(days=12)
        for a, b in chunks(ev_start, ev_end, 150):
            data = get_json(HEBCAL_EVENTS, {
                "v": 1, "cfg": "json", "start": a.isoformat(), "end": b.isoformat(),
                "M": "on", "b": loc.get("candle_lighting_minutes", 18),
                "c": "on", "s": "on", "maj": "on", "min": "on", "mod": "on",
                "nx": "on", "mf": "on", "ss": "off", **loc_params(loc)})
            for it in data.get("items", []):
                self._add_event(it)
        self.candles.sort()
        self.havdalah.sort()

        for a, b in chunks(ev_start, ev_end, 60):
            data = get_json(HEBCAL_ZMANIM, {
                "cfg": "json", "start": a.isoformat(), "end": b.isoformat(),
                **loc_params(loc)})
            for key, by_date in data.get("times", {}).items():
                if isinstance(by_date, dict):
                    self.zmanim.setdefault(key, {}).update(by_date)

        # A one-day range returns a different JSON shape, so always ask for 2+.
        for a, b in chunks(start, end + dt.timedelta(days=1), 150):
            data = get_json(HEBCAL_CONVERT, {
                "cfg": "json", "start": a.isoformat(), "end": b.isoformat(),
                "g2h": 1})
            self.hdates.update(data.get("hdates", {}))

    def _add_event(self, it: dict[str, Any]) -> None:
        cat, raw = it.get("category"), it.get("date", "")
        if cat in ("candles", "havdalah"):
            when = dt.datetime.fromisoformat(raw).astimezone(self.tz)
            (self.candles if cat == "candles" else self.havdalah).append(when)
            return
        day = dt.date.fromisoformat(raw[:10])
        he = it.get("hebrew", "")
        if cat == "parashat":
            self.parsha[day] = he
        elif cat in ("holiday", "roshchodesh") and he:
            self.holidays.setdefault(day, []).append((he, bool(it.get("yomtov"))))

    def zman(self, key: str, day: dt.date) -> dt.datetime | None:
        raw = self.zmanim.get(key, {}).get(day.isoformat())
        return dt.datetime.fromisoformat(raw).astimezone(self.tz) if raw else None

    def hebrew_date(self, day: dt.date) -> str:
        parts = self.hdates.get(day.isoformat(), {}).get("heDateParts")
        return f"{parts['d']} {parts['m']} {parts['y']}" if parts else ""

    def today_notes(self, day: dt.date) -> str:
        names = [n for n, _ in self.holidays.get(day, [])]
        return "  ·  ".join(names[:2])

    def upcoming(self, day: dt.date) -> dict[str, Any]:
        """The Shabbos / Yom Tov that `day` is in or heading towards."""
        hav = next((h for h in self.havdalah if h.date() >= day), None)
        if hav is None:
            return {}
        prev = [h for h in self.havdalah if h < hav]
        since = prev[-1] if prev else dt.datetime.min.replace(tzinfo=self.tz)
        stretch = [c for c in self.candles if since < c < hav]
        ahead = [c for c in stretch if c.date() >= day]
        candles = ahead[0] if ahead else (stretch[-1] if stretch else None)

        first = stretch[0].date() if stretch else hav.date()
        days = [first + dt.timedelta(days=i)
                for i in range((hav.date() - first).days + 1)]
        parsha = next((self.parsha[d] for d in days if d in self.parsha), None)
        yomtov = next((n for d in days for n, yt in self.holidays.get(d, []) if yt),
                      None)
        is_shabbos = hav.date().weekday() == 5
        heading = "שבת קודש" if is_shabbos else "יום טוב"
        if is_shabbos and yomtov:
            heading = "יום טוב ושבת קודש"
        return {
            "heading": heading,
            "title": parsha or yomtov or "",
            "candles": candles,
            "havdalah": hav,
            "rabbeinu_tam": self.zman("tzeit72min", hav.date()),
        }


def fetch_weather(loc: dict[str, Any], unit: str) -> dict[str, Any]:
    return get_json(OPEN_METEO, {
        "latitude": loc["latitude"], "longitude": loc["longitude"],
        "current": "temperature_2m,weather_code",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "timezone": loc["timezone"], "forecast_days": 2,
        "temperature_unit": unit})


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------
def ensure_font() -> None:
    if not FONT_PATH.exists():
        FONT_PATH.parent.mkdir(exist_ok=True)
        r = requests.get(FONT_URL, timeout=60)
        r.raise_for_status()
        FONT_PATH.write_bytes(r.content)


class Canvas:
    def __init__(self, width: int, height: int):
        self.img = Image.new("L", (width, height), 255)
        self.draw = ImageDraw.Draw(self.img)
        self.w, self.h = width, height
        self._fonts: dict[tuple[int, int], ImageFont.FreeTypeFont] = {}

    def font(self, size: int, weight: int) -> ImageFont.FreeTypeFont:
        key = (size, weight)
        if key not in self._fonts:
            f = ImageFont.truetype(str(FONT_PATH), size)
            f.set_variation_by_axes([weight])
            self._fonts[key] = f
        return self._fonts[key]

    def text(self, xy, txt, size, weight=400, fill=0, anchor="ma"):
        self.draw.text(xy, txt, font=self.font(size, weight), fill=fill,
                       anchor=anchor)

    def hline(self, y, width=3):
        self.draw.line([(40, y), (self.w - 40, y)], fill=0, width=width)


def fmt_time(d: dt.datetime | None) -> str:
    return d.strftime("%I:%M").lstrip("0") if d else "—"


def draw_header(c: Canvas, cal: Calendar, day: dt.date) -> int:
    cx = c.w // 2
    c.text((cx, 28), HEB_WEEKDAY[day.weekday()], 76, 800)
    c.text((cx, 128), cal.hebrew_date(day), 58, 500)
    c.text((cx, 206), f"{day.day}/{day.month}/{day.year}", 34, 400)
    notes = cal.today_notes(day)
    if notes:
        c.text((cx, 252), notes, 34, 600)
    c.hline(308)
    return 308


def draw_shabbos(c: Canvas, cal: Calendar, day: dt.date, y: int) -> int:
    info = cal.upcoming(day)
    cx = c.w // 2
    if not info:
        return y
    c.text((cx, y + 18), info["heading"], 60, 800)
    if info["title"]:
        c.text((cx, y + 98), info["title"], 54, 600)

    top, pad = y + 190, 40
    box_w = (c.w - 3 * pad) // 2

    def box(x0: int, label: str, value: str) -> None:
        c.draw.rectangle((x0, top, x0 + box_w, top + 230), outline=0, width=4)
        c.text((x0 + box_w // 2, top + 18), label, 40, 600)
        c.text((x0 + box_w // 2, top + 72), value, 118, 800)

    # Right-hand box first: Hebrew reads right to left.
    box(pad + box_w + pad, "הדלקת נרות", fmt_time(info["candles"]))
    box(pad, "רבינו תם", fmt_time(info["rabbeinu_tam"]))
    c.text((cx, top + 250), f"הבדלה  {fmt_time(info['havdalah'])}", 44, 600)
    c.hline(top + 326)
    return top + 326


def draw_zmanim(c: Canvas, cal: Calendar, day: dt.date, y: int) -> None:
    cx = c.w // 2
    c.text((cx, y + 14), "זמני היום", 50, 800)
    rows = [(label, cal.zman(key, day)) for label, key in ZMANIM_ROWS]
    half = (len(rows) + 1) // 2
    row_h, top = 76, y + 100
    # Two columns; the right column is read first.
    for col, part in enumerate((rows[:half], rows[half:])):
        right = c.w - 50 if col == 0 else cx - 30
        left = cx + 30 if col == 0 else 50
        for i, (label, when) in enumerate(part):
            yy = top + i * row_h
            c.text((right, yy), label, 36, 500, anchor="ra")
            c.text((left, yy - 4), fmt_time(when), 42, 700, anchor="la")
    c.draw.line([(cx, top), (cx, top + half * row_h - 20)], fill=0, width=2)


def draw_weather(c: Canvas, weather: dict[str, Any], now: dt.datetime,
                 y: int, unit_label: str) -> None:
    cx = c.w // 2
    cur = weather.get("current", {})
    temp, code = cur.get("temperature_2m"), cur.get("weather_code", 0)
    c.text((cx, y + 14), "מזג האוויר", 46, 800)
    if temp is not None:
        c.text((cx, y + 76), f"{temp:.0f}{unit_label}  ·  {WMO_HE.get(code, '')}",
               42, 600)

    hourly = weather.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    pops = hourly.get("precipitation_probability") or [0] * len(times)
    codes = hourly.get("weather_code", [])
    now_key = now.strftime("%Y-%m-%dT%H")
    start = next((i for i, t in enumerate(times) if t[:13] >= now_key), 0)
    hours = list(range(start, min(start + 10, len(times))))
    if not hours:
        return

    top, bottom = y + 150, c.h - 60
    col_w = (c.w - 80) // len(hours)
    for k, i in enumerate(hours):
        x = 40 + k * col_w + col_w // 2
        pop = pops[i] if i < len(pops) and pops[i] is not None else 0
        code = codes[i] if i < len(codes) else 0
        wet = code in WET_CODES or pop >= 50
        fill = 0
        if wet:
            c.draw.rectangle((x - col_w // 2 + 4, top, x + col_w // 2 - 4, bottom),
                             fill=0)
            fill = 255
        hour = int(times[i][11:13])
        c.text((x, top + 12), f"{hour}:00", 28, 600, fill=fill)
        if i < len(temps) and temps[i] is not None:
            c.text((x, top + 62), f"{temps[i]:.0f}°", 46, 800, fill=fill)
        c.text((x, top + 132), f"{int(pop)}%", 30, 400, fill=fill)
        word = WMO_HE.get(code, "").split(" ")[0]
        c.text((x, top + 182), word, 24, 500, fill=fill)


def render_page(cfg: dict[str, Any], cal: Calendar, day: dt.date, *,
                weather: dict[str, Any] | None = None,
                now: dt.datetime | None = None) -> Image.Image:
    disp = cfg["display"]
    c = Canvas(disp["width"], disp["height"])
    y = draw_header(c, cal, day)
    y = draw_shabbos(c, cal, day, y)
    if weather is not None and now is not None:
        unit = cfg.get("temperature_unit", "celsius")
        draw_weather(c, weather, now, y, "°F" if unit == "fahrenheit" else "°C")
        footer = f"{cfg.get('city_he', '')}  ·  עודכן {now.strftime('%H:%M')}"
    else:
        draw_zmanim(c, cal, day, y)
        footer = cfg.get("city_he", "")
    c.text((c.w // 2, c.h - 44), footer, 26, 400)
    img = c.img
    if disp.get("rotate", 0):
        img = img.rotate(disp["rotate"], expand=True)
    return img


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_live(cfg: dict[str, Any], out: Path, stamp: Path | None) -> None:
    loc = cfg["location"]
    now = dt.datetime.now(ZoneInfo(loc["timezone"]))
    cal = Calendar(loc, now.date(), now.date())
    try:
        weather = fetch_weather(loc, cfg.get("temperature_unit", "celsius"))
    except Exception as e:  # noqa: BLE001 - a page without weather beats no page
        print(f"weather unavailable ({e}); rendering zmanim instead", file=sys.stderr)
        weather = None
    img = render_page(cfg, cal, now.date(), weather=weather, now=now)
    img.save(out, "PNG", optimize=True)
    if stamp:
        # The device ignores a live image whose stamp is too old.
        stamp.write_text(f"{int(now.timestamp())}\n", encoding="ascii", newline="\n")
    print(f"wrote {out}", file=sys.stderr)


def cmd_pack(cfg: dict[str, Any], out_dir: Path, start: dt.date, days: int) -> None:
    loc = cfg["location"]
    end = start + dt.timedelta(days=days - 1)
    print(f"fetching calendar {start} .. {end}", file=sys.stderr)
    cal = Calendar(loc, start, end)
    out_dir.mkdir(parents=True, exist_ok=True)
    for i in range(days):
        day = start + dt.timedelta(days=i)
        render_page(cfg, cal, day).save(out_dir / f"{day.isoformat()}.png",
                                        "PNG", optimize=True)
    print(f"wrote {days} pages to {out_dir}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["live", "pack"])
    ap.add_argument("--config", default=str(Path(__file__).parent / "config.json"))
    ap.add_argument("--out", default="dashboard.png")
    ap.add_argument("--stamp", default=None)
    ap.add_argument("--out-dir", default="pages")
    ap.add_argument("--start", default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--days", type=int, default=400)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    ensure_font()
    if not features.check("raqm"):
        print("WARNING: Pillow has no raqm; Hebrew will render reversed. "
              "Install libfribidi.", file=sys.stderr)

    if args.command == "live":
        cmd_live(cfg, Path(args.out), Path(args.stamp) if args.stamp else None)
    else:
        tz = ZoneInfo(cfg["location"]["timezone"])
        start = (dt.date.fromisoformat(args.start) if args.start
                 else dt.datetime.now(tz).date())
        cmd_pack(cfg, Path(args.out_dir), start, args.days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
