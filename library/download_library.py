"""
Build the offline Hebrew library (Tanakh, Siddur, Shas) as EPUBs from
Sefaria's public API, laid out for reading in KOReader on the Kobo.

Hebrew only: Hebrew titles, headings, perek/pasuk/daf numbering, RTL page
progression. One HTTP call per book, cached under library/cache/.

Usage:
    python download_library.py all
    python download_library.py tanakh | shas | siddur
    python download_library.py one "Berakhot"

Output: library/output/<folder>/<NN shem ha-sefer>.epub
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from html import escape
from pathlib import Path

import lxml.etree
import lxml.html
import requests
from ebooklib import epub

API = "https://www.sefaria.org/api"
USER_AGENT = "kobo-shabbos-library/1.0"

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
OUT = ROOT / "output"
MANIFEST = ROOT / "library_manifest.json"

# Sefaria index name -> shem ha-sefer.
HEBREW_TITLES = {
    # Tanakh
    "Genesis": "בראשית", "Exodus": "שמות", "Leviticus": "ויקרא",
    "Numbers": "במדבר", "Deuteronomy": "דברים",
    "Joshua": "יהושע", "Judges": "שופטים",
    "I Samuel": "שמואל א", "II Samuel": "שמואל ב",
    "I Kings": "מלכים א", "II Kings": "מלכים ב",
    "Isaiah": "ישעיה", "Jeremiah": "ירמיה", "Ezekiel": "יחזקאל",
    "Hosea": "הושע", "Joel": "יואל", "Amos": "עמוס",
    "Obadiah": "עובדיה", "Jonah": "יונה", "Micah": "מיכה",
    "Nahum": "נחום", "Habakkuk": "חבקוק", "Zephaniah": "צפניה",
    "Haggai": "חגי", "Zechariah": "זכריה", "Malachi": "מלאכי",
    "Psalms": "תהילים", "Proverbs": "משלי", "Job": "איוב",
    "Song of Songs": "שיר השירים", "Ruth": "רות",
    "Lamentations": "איכה", "Ecclesiastes": "קהלת", "Esther": "אסתר",
    "Daniel": "דניאל", "Ezra": "עזרא", "Nehemiah": "נחמיה",
    "I Chronicles": "דברי הימים א", "II Chronicles": "דברי הימים ב",
    # Shas Bavli
    "Berakhot": "ברכות", "Shabbat": "שבת", "Eruvin": "עירובין",
    "Pesachim": "פסחים", "Yoma": "יומא", "Sukkah": "סוכה",
    "Beitzah": "ביצה", "Rosh Hashanah": "ראש השנה",
    "Taanit": "תענית", "Megillah": "מגילה", "Moed Katan": "מועד קטן",
    "Chagigah": "חגיגה",
    "Yevamot": "יבמות", "Ketubot": "כתובות", "Nedarim": "נדרים",
    "Nazir": "נזיר", "Sotah": "סוטה", "Gittin": "גיטין",
    "Kiddushin": "קידושין",
    "Bava Kamma": "בבא קמא", "Bava Metzia": "בבא מציעא",
    "Bava Batra": "בבא בתרא",
    "Sanhedrin": "סנהדרין", "Makkot": "מכות", "Shevuot": "שבועות",
    "Avodah Zarah": "עבודה זרה", "Horayot": "הוריות",
    "Zevachim": "זבחים", "Menachot": "מנחות", "Chullin": "חולין",
    "Bekhorot": "בכורות", "Arakhin": "ערכין", "Temurah": "תמורה",
    "Keritot": "כריתות", "Meilah": "מעילה", "Tamid": "תמיד",
    "Niddah": "נדה",
    "Jerusalem Talmud Shekalim": "שקלים (ירושלמי)",
    "Siddur Ashkenaz": "סידור אשכנז",
}

# No embedded font: KOReader shapes nikud and te'amim with its own configured
# font (HarfBuzz), which is what makes the Hebrew read properly.
EPUB_CSS = """\
body { direction: rtl; text-align: justify; line-height: 1.6; }
h1, h2, h3 { text-align: center; text-indent: 0; }
h2 { font-size: 1.25em; margin: 0.4em 0 0.8em 0; }
h3 { font-size: 1.05em; margin: 0.8em 0 0.4em 0; }
p { margin: 0 0 0.7em 0; text-indent: 0; }
.v { font-size: 0.6em; font-weight: bold; color: #555555; vertical-align: 0.35em; }
big { font-size: 1.25em; }
small { font-size: 0.8em; }
"""


def hebrew_title(english_title: str) -> str:
    return HEBREW_TITLES.get(english_title, english_title)


# ---------------------------------------------------------------------------
# HTTP + cache
# ---------------------------------------------------------------------------
def http_get_json(url: str, params: dict | None = None, retries: int = 4) -> dict:
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=180,
                             headers={"User-Agent": USER_AGENT})
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 ** attempt)
    raise RuntimeError(f"GET {url} failed after {retries}: {last}")


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


def _cached(kind: str, name: str, url: str, params: dict | None) -> dict:
    p = CACHE / kind / f"{slug(name)}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    print(f"  fetching {name} ...", file=sys.stderr)
    data = http_get_json(url, params)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


_TEXT_PARAMS = {"context": 0, "pad": 0, "commentary": 0}


def fetch_index_bulk(title: str) -> dict:
    """Whole book in one call. Complex schemas (Siddur) return 400 here."""
    return _cached("index", title, f"{API}/texts/{title}", _TEXT_PARAMS)


def fetch_index_meta(title: str) -> dict:
    return _cached("meta", title, f"{API}/index/{title}", None)


def fetch_ref_bulk(ref: str) -> dict:
    return _cached("ref", ref, f"{API}/texts/{ref}", _TEXT_PARAMS)


def schema_leaves(title: str, schema: dict) -> list[tuple[list[str], list[str]]]:
    """(english_path, hebrew_path) per leaf; the ref is ", ".join(english_path)."""
    out: list[tuple[list[str], list[str]]] = []

    def walk(node: dict, path: list[str], he_path: list[str]) -> None:
        children = node.get("nodes")
        if children:
            for child in children:
                t = child.get("title") or child.get("key") or "?"
                walk(child, path + [t], he_path + [child.get("heTitle") or t])
        else:
            out.append((path, he_path))

    walk({"nodes": schema.get("nodes", [])}, [title], [title])
    return out


# ---------------------------------------------------------------------------
# Hebrew numerals
# ---------------------------------------------------------------------------
def gematria(n: int) -> str:
    out = ""
    while n >= 400:
        out += "ת"
        n -= 400
    for val, ch in ((300, "ש"), (200, "ר"), (100, "ק")):
        if n >= val:
            out += ch
            n -= val
    if n in (15, 16):
        return out + ("טו" if n == 15 else "טז")
    if n >= 10:
        out += "יכלמנסעפצ"[n // 10 - 1]
        n %= 10
    if n:
        out += "אבגדהוזחט"[n - 1]
    return out


def gershayim(s: str) -> str:
    return s + "׳" if len(s) == 1 else s[:-1] + "״" + s[-1]


# ---------------------------------------------------------------------------
# Sefaria HTML fragments -> well-formed XHTML
# ---------------------------------------------------------------------------
def clean(line: str) -> str:
    frag = lxml.html.fragment_fromstring(line, create_parent="span")
    for el in frag.xpath('.//sup[contains(@class,"footnote-marker")]'
                         ' | .//i[contains(@class,"footnote")]'):
        el.drop_tree()
    for el in frag.iter():
        for attr in list(el.attrib):
            del el.attrib[attr]
    return lxml.etree.tostring(frag, encoding="unicode", method="xml")


def _flatten(arr) -> list[str]:
    out = []
    if isinstance(arr, list):
        for x in arr:
            out.extend(_flatten(x))
    elif arr:
        out.append(str(arr))
    return out


def tanakh_html(heading: str, verses: list) -> str:
    """One perek: verses flow inline; new paragraph after each {פ} break."""
    paras: list[list[str]] = [[]]
    for i, verse in enumerate(verses, 1):
        if not verse:
            continue
        paras[-1].append(f'<span class="v">{gematria(i)}</span>&#160;{clean(verse)}')
        if "{פ}" in verse:
            paras.append([])
    body = "\n".join(f"<p>{' '.join(p)}</p>" for p in paras if p)
    return f"<h2>{escape(heading)}</h2>\n{body}"


def plain_html(heading: str, block, sub_label: str | None = None) -> str:
    """Talmud daf / siddur section: one paragraph per segment, unnumbered."""
    parts = [f"<h2>{escape(heading)}</h2>"]
    nested = isinstance(block, list) and block and isinstance(block[0], list)
    if sub_label and nested:
        for j, sub in enumerate(block, 1):
            lines = _flatten(sub)
            if lines:
                parts.append(f"<h3>{sub_label} {gershayim(gematria(j))}</h3>")
                parts.extend(f"<p>{clean(x)}</p>" for x in lines)
    else:
        parts.extend(f"<p>{clean(x)}</p>" for x in _flatten(block))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# EPUB
# ---------------------------------------------------------------------------
def new_book(title: str) -> epub.EpubBook:
    book = epub.EpubBook()
    book.set_identifier(f"kobo-shabbos:{slug(title)}:he")
    book.set_title(hebrew_title(title))
    book.set_language("he")
    book.set_direction("rtl")  # right-to-left page progression
    book.add_author("ספריא")
    book.add_item(epub.EpubItem(uid="style", file_name="style.css",
                                media_type="text/css",
                                content=EPUB_CSS.encode("utf-8")))
    return book


def add_chapter(book: epub.EpubBook, idx: int, label: str, body: str) -> epub.EpubHtml:
    ch = epub.EpubHtml(title=label, file_name=f"sec_{idx:04d}.xhtml",
                       lang="he", direction="rtl")
    ch.content = f'<div dir="rtl">{body}</div>'
    ch.add_item(book.get_item_with_id("style"))
    book.add_item(ch)
    return ch


def finish(book: epub.EpubBook, toc, chapters: list, out_path: Path) -> None:
    book.toc = toc
    book.spine = chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book)
    print(f"  -> {slug(out_path.stem) or out_path.stem} ({len(chapters)} sections)",
          file=sys.stderr)


def build_simple(title: str, data: dict, out_path: Path) -> None:
    he_title = hebrew_title(title)
    book = new_book(title)
    address = data.get("addressTypes") or []
    chapters = []
    for i, block in enumerate(data.get("he") or []):
        if not _flatten(block):
            continue
        if address and address[0] == "Talmud":
            # Slots 0/1 are the nonexistent daf 1; 2a lives at index 2.
            daf = gershayim(gematria(i // 2 + 1))
            label = f"דף {daf} ע״{'א' if i % 2 == 0 else 'ב'}"
            body = plain_html(f"{he_title} {label}", block)
        elif len(address) == 2:
            label = f"פרק {gershayim(gematria(i + 1))}"
            body = tanakh_html(f"{he_title} {label}", block)
        else:
            label = f"פרק {gershayim(gematria(i + 1))}"
            body = plain_html(f"{he_title} {label}", block, sub_label="הלכה")
        chapters.append(add_chapter(book, i, label, body))
    finish(book, tuple(chapters), chapters, out_path)


def build_complex(title: str, meta: dict, out_path: Path) -> None:
    book = new_book(title)
    chapters: list[epub.EpubHtml] = []
    groups: dict[str, list[epub.EpubHtml]] = {}
    for idx, (path, he_path) in enumerate(schema_leaves(title, meta.get("schema", {}))):
        try:
            data = fetch_ref_bulk(", ".join(path))
        except Exception as e:  # noqa: BLE001
            print(f"    skipping {', '.join(path)}: {e}", file=sys.stderr)
            continue
        he = data.get("he") or []
        if not _flatten(he):
            continue
        label = he_path[-1]
        ch = add_chapter(book, idx, label, plain_html(label, he))
        chapters.append(ch)
        groups.setdefault(" · ".join(he_path[1:-1]) or label, []).append(ch)
    toc = tuple((epub.Section(name), tuple(chs)) for name, chs in groups.items())
    finish(book, toc, chapters, out_path)


# ---------------------------------------------------------------------------
# Build flow
# ---------------------------------------------------------------------------
CATEGORIES = [("tanakh", "1 תנך"), ("siddur", "2 סידור"), ("shas_bavli", "3 שס")]


def build_one(title: str, out_path: Path) -> None:
    meta = fetch_index_meta(title)
    if meta.get("schema", {}).get("nodes"):
        build_complex(title, meta, out_path)
    else:
        build_simple(title, fetch_index_bulk(title), out_path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["tanakh", "shas", "siddur", "all", "one"])
    ap.add_argument("title", nargs="?", help="(for 'one') Sefaria index title")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if args.command == "one":
        if not args.title:
            ap.error("'one' requires a title")
        build_one(args.title, OUT / "custom" / f"{hebrew_title(args.title)}.epub")
        return 0

    wanted = {"tanakh": ["tanakh"], "shas": ["shas_bavli"], "siddur": ["siddur"],
              "all": [k for k, _ in CATEGORIES]}[args.command]
    failed = []
    for key, folder in CATEGORIES:
        if key not in wanted:
            continue
        for n, t in enumerate(manifest[key], 1):
            if isinstance(t, dict):
                t = t.get("sefaria_index") or t.get("title")
            # Numeric prefix keeps the canonical order in the file browser.
            out = OUT / folder / f"{n:02d} {hebrew_title(t)}.epub"
            try:
                build_one(t, out)
            except Exception as e:  # noqa: BLE001
                failed.append(t)
                print(f"!! {t} failed: {e!r}", file=sys.stderr)
    print(f"done. failed: {failed or 'none'}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
