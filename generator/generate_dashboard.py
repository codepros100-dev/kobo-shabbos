"""
Generate a Shabbos/Zmanim/Weather dashboard PNG sized for the Kobo Clara HD
(1072x1448, 8-bit grayscale).

Data sources (all free, no API key):
  - Hebcal Shabbat API  : candle lighting, havdalah, parsha
  - Hebcal Zmanim API   : Rabbeinu Tam (tzeit 72 min) for the upcoming motzei
  - Hebcal Converter API: Hebrew date
  - Open-Meteo          : current temp + hourly forecast

Usage:
    python generate_dashboard.py --config config.json --out dashboard.png
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont

HEBCAL_SHABBAT = "https://www.hebcal.com/shabbat"
HEBCAL_ZMANIM = "https://www.hebcal.com/zmanim"
HEBCAL_CONVERT = "https://www.hebcal.com/converter"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

FONT_URLS = {
    "sans": "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf",
    "sans_bold": "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Bold.ttf",
    "hebrew": "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansHebrew/NotoSansHebrew-Regular.ttf",
    "hebrew_bold": "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansHebrew/NotoSansHebrew-Bold.ttf",
}

# WMO weather codes -> short text (Open-Meteo)
WMO = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Showers", 81: "Heavy showers", 82: "Violent showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm + hail", 99: "Thunderstorm + hail",
}
WET_CODES = set(range(51, 68)) | set(range(80, 83)) | {95, 96, 99}


@dataclass
class Location:
    city_label: str
    latitude: float
    longitude: float
    timezone: str
    geonameid: int | None
    candle_lighting_minutes: int = 18


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
def font_dir() -> Path:
    p = Path(__file__).parent / "fonts"
    p.mkdir(exist_ok=True)
    return p


def ensure_fonts() -> dict[str, Path]:
    out = {}
    for name, url in FONT_URLS.items():
        path = font_dir() / f"{name}.ttf"
        if not path.exists():
            print(f"  downloading font {name} ...", file=sys.stderr)
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            path.write_bytes(r.content)
        out[name] = path
    return out


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
def fetch_shabbat(loc: Location) -> dict[str, Any]:
    params = {
        "cfg": "json",
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "tzid": loc.timezone,
        "M": "on",
        "b": loc.candle_lighting_minutes,
    }
    if loc.geonameid:
        params = {"cfg": "json", "geonameid": loc.geonameid,
                  "M": "on", "b": loc.candle_lighting_minutes}
    r = requests.get(HEBCAL_SHABBAT, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_zmanim_for(loc: Location, date: dt.date) -> dict[str, Any]:
    params = {
        "cfg": "json",
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "tzid": loc.timezone,
        "date": date.isoformat(),
    }
    r = requests.get(HEBCAL_ZMANIM, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_hebrew_date(date: dt.date) -> dict[str, Any]:
    params = {"cfg": "json", "gy": date.year, "gm": date.month, "gd": date.day,
              "g2h": 1, "strict": 1}
    r = requests.get(HEBCAL_CONVERT, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_weather(loc: Location) -> dict[str, Any]:
    params = {
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "current": "temperature_2m,weather_code",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "timezone": loc.timezone,
        "forecast_days": 2,
        "temperature_unit": "celsius",
    }
    r = requests.get(OPEN_METEO, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def upcoming_saturday(today: dt.date) -> dt.date:
    # Mon=0 .. Sun=6 ; Saturday=5
    delta = (5 - today.weekday()) % 7
    if delta == 0 and today.weekday() != 5:
        delta = 7
    return today + dt.timedelta(days=delta)


def parse_iso(s: str) -> dt.datetime:
    # Hebcal returns ISO8601 with offset
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def fmt_time(d: dt.datetime, tz: ZoneInfo) -> str:
    return d.astimezone(tz).strftime("%I:%M %p").lstrip("0")


def extract_shabbat_info(data: dict[str, Any], tz: ZoneInfo) -> dict[str, Any]:
    items = data.get("items", [])
    out: dict[str, Any] = {"parsha": None, "parsha_he": None,
                           "candles": None, "havdalah": None}
    for it in items:
        cat = it.get("category")
        if cat == "candles" and out["candles"] is None:
            out["candles"] = parse_iso(it["date"])
        elif cat == "havdalah" and out["havdalah"] is None:
            out["havdalah"] = parse_iso(it["date"])
        elif cat == "parashat":
            out["parsha"] = it.get("title", "").replace("Parashat ", "")
            out["parsha_he"] = it.get("hebrew", "")
    return out


def extract_rt(zmanim_data: dict[str, Any]) -> dt.datetime | None:
    # zmanim API returns a `times` dict; field name has varied across versions
    times = zmanim_data.get("times", {})
    for key in ("tzeit72min", "tzeit72", "tzeit_72min"):
        if key in times:
            return parse_iso(times[key])
    return None


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------
class Canvas:
    def __init__(self, width: int, height: int, fonts: dict[str, Path]):
        self.img = Image.new("L", (width, height), 255)
        self.draw = ImageDraw.Draw(self.img)
        self.w, self.h = width, height
        self.fonts = fonts
        self._cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

    def f(self, name: str, size: int) -> ImageFont.FreeTypeFont:
        key = (name, size)
        if key not in self._cache:
            self._cache[key] = load_font(self.fonts[name], size)
        return self._cache[key]

    def text(self, xy, txt, font, fill=0, anchor="la"):
        self.draw.text(xy, txt, font=font, fill=fill, anchor=anchor)

    def text_w(self, txt: str, font) -> int:
        bbox = self.draw.textbbox((0, 0), txt, font=font)
        return bbox[2] - bbox[0]

    def hline(self, y, x0=40, x1=None, fill=0, width=2):
        if x1 is None:
            x1 = self.w - 40
        self.draw.line([(x0, y), (x1, y)], fill=fill, width=width)

    def rect(self, xy, fill=None, outline=0, width=2):
        self.draw.rectangle(xy, fill=fill, outline=outline, width=width)


def render(cfg: dict[str, Any], out_path: Path) -> None:
    loc = Location(**cfg["location"])
    tz = ZoneInfo(loc.timezone)
    now = dt.datetime.now(tz)

    print("Fetching Hebcal Shabbat ...", file=sys.stderr)
    shabbat = fetch_shabbat(loc)
    si = extract_shabbat_info(shabbat, tz)

    target_sat = upcoming_saturday(now.date())
    print(f"Fetching zmanim for {target_sat} ...", file=sys.stderr)
    zm = fetch_zmanim_for(loc, target_sat)
    rt = extract_rt(zm)

    print("Fetching Hebrew date ...", file=sys.stderr)
    hd = fetch_hebrew_date(now.date())

    print("Fetching weather ...", file=sys.stderr)
    weather = fetch_weather(loc)

    fonts = ensure_fonts()
    disp = cfg["display"]
    c = Canvas(disp["width"], disp["height"], fonts)

    # ---- Header ----
    header_y = 50
    c.text((c.w // 2, header_y),
           now.strftime("%A, %B %-d, %Y") if os.name != "nt"
           else now.strftime("%A, %B %#d, %Y"),
           c.f("sans_bold", 44), anchor="ma")

    heb = hd.get("hebrew", "")
    if heb:
        c.text((c.w // 2, header_y + 65), heb,
               c.f("hebrew", 50), anchor="ma")

    c.text((c.w // 2, header_y + 130), loc.city_label,
           c.f("sans", 32), anchor="ma")

    c.hline(header_y + 195)

    # ---- Shabbos block ----
    y = header_y + 235
    c.text((c.w // 2, y), "Shabbos", c.f("sans_bold", 56), anchor="ma")
    if si["parsha"]:
        line = f"Parshas {si['parsha']}"
        c.text((c.w // 2, y + 80), line, c.f("sans", 40), anchor="ma")
    if si["parsha_he"]:
        c.text((c.w // 2, y + 135), si["parsha_he"],
               c.f("hebrew_bold", 48), anchor="ma")

    # Big times
    times_y = y + 230
    box_w = (c.w - 120) // 2
    pad = 40

    def time_box(x0, label, value):
        c.rect((x0, times_y, x0 + box_w, times_y + 240), outline=0, width=3)
        c.text((x0 + box_w // 2, times_y + 30), label,
               c.f("sans_bold", 36), anchor="ma")
        c.text((x0 + box_w // 2, times_y + 100), value,
               c.f("sans_bold", 96), anchor="ma")

    candles = (fmt_time(si["candles"], tz) if si["candles"] else "—")
    time_box(pad, "Candle Lighting", candles)

    rt_str = fmt_time(rt, tz) if rt else "—"
    time_box(pad + box_w + pad, "Rabbeinu Tam", rt_str)

    if si["havdalah"]:
        hav = fmt_time(si["havdalah"], tz)
        c.text((c.w // 2, times_y + 270),
               f"Standard havdalah (motzei Shabbos): {hav}",
               c.f("sans", 28), anchor="ma")

    # ---- Weather block ----
    wy = times_y + 330
    c.hline(wy)
    wy += 30
    c.text((c.w // 2, wy), "Weather", c.f("sans_bold", 48), anchor="ma")

    cur = weather.get("current", {})
    cur_t = cur.get("temperature_2m")
    cur_code = cur.get("weather_code", 0)
    cur_label = WMO.get(cur_code, "—")
    if cur_t is not None:
        c.text((c.w // 2, wy + 75),
               f"{cur_t:.0f}°C   {cur_label}",
               c.f("sans", 44), anchor="ma")

    # Hourly forecast — next 12 hours
    hourly = weather.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    pops = hourly.get("precipitation_probability", []) or [0] * len(times)
    codes = hourly.get("weather_code", [])

    # find first index >= now
    now_iso = now.replace(minute=0, second=0, microsecond=0).isoformat()[:13]
    start_idx = 0
    for i, t in enumerate(times):
        if t[:13] >= now_iso:
            start_idx = i
            break

    hours = list(range(start_idx, min(start_idx + 12, len(times))))
    if hours:
        col_w = (c.w - 80) // len(hours)
        chart_top = wy + 160
        chart_h = 280
        chart_bot = chart_top + chart_h

        # temp scale
        sel_temps = [temps[i] for i in hours if temps[i] is not None]
        if sel_temps:
            tmin, tmax = min(sel_temps), max(sel_temps)
            if tmax - tmin < 4:
                tmax = tmin + 4
        else:
            tmin, tmax = 0.0, 1.0

        for k, i in enumerate(hours):
            x = 40 + k * col_w + col_w // 2
            t_iso = times[i]
            try:
                hh = dt.datetime.fromisoformat(t_iso).strftime("%-Hh") \
                    if os.name != "nt" \
                    else dt.datetime.fromisoformat(t_iso).strftime("%#Hh")
            except ValueError:
                hh = t_iso[11:13] + "h"
            temp = temps[i] if i < len(temps) else None
            pop = pops[i] if i < len(pops) else 0
            code = codes[i] if i < len(codes) else 0
            wet = code in WET_CODES or (pop is not None and pop >= 50)

            # rain hour: solid black band behind column
            if wet:
                c.rect((x - col_w // 2 + 4, chart_top,
                        x + col_w // 2 - 4, chart_bot),
                       fill=0)
                txt_fill = 255
            else:
                txt_fill = 0

            # hour label
            c.text((x, chart_top + 10), hh,
                   c.f("sans_bold", 26), fill=txt_fill, anchor="ma")
            if temp is not None:
                c.text((x, chart_top + 60), f"{temp:.0f}°",
                       c.f("sans_bold", 38), fill=txt_fill, anchor="ma")
            if pop is not None:
                c.text((x, chart_top + 130), f"{int(pop)}%",
                       c.f("sans", 28), fill=txt_fill, anchor="ma")
            # weather word, abbreviated
            label = WMO.get(code, "")
            if label:
                short = label.split()[0][:6]
                c.text((x, chart_top + 180), short,
                       c.f("sans", 22), fill=txt_fill, anchor="ma")

        # Legend / footer
        c.text((c.w // 2, chart_bot + 25),
               "Black columns = rain / precipitation expected",
               c.f("sans", 22), anchor="ma")

    # ---- Footer: last update ----
    footer = f"Updated {now.strftime('%a %b %d %H:%M %Z')}"
    c.text((c.w // 2, c.h - 40), footer, c.f("sans", 22), anchor="ma")

    # rotate if requested
    if disp.get("rotate", 0):
        c.img = c.img.rotate(disp["rotate"], expand=True)

    c.img.save(out_path, "PNG", optimize=True)
    print(f"wrote {out_path}", file=sys.stderr)


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--out", default="dashboard.png")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"config not found: {cfg_path}", file=sys.stderr)
        print("copy config.example.json to config.json and edit it",
              file=sys.stderr)
        return 2
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    render(cfg, Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
