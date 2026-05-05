"""
Download a Jewish reference library (Tanakh incl. Tehillim, full Shas Bavli,
Siddur) from Sefaria's public API and bundle each work as an EPUB ready to
copy to a Kobo.

Sources:
  - Hebrew text: Sefaria's CC-licensed Vilna / WLC editions (public domain).
  - English: William Davidson Talmud (CC-BY-NC) and Sefaria community
    translations of Tanakh / Siddurim. License terms are added to each EPUB.

Network strategy:
  One HTTP call per index (book / masechta) using /api/texts/<index>?context=0,
  not one per section. Empirically ~1-3s per index instead of ~10-30 min,
  so the full library finishes in single-digit minutes.

Usage:
    python download_library.py tanakh              # all of Tanakh
    python download_library.py shas                # full Shas (37 Bavli + Yerushalmi Shekalim)
    python download_library.py siddur              # configured siddurim
    python download_library.py all                 # everything in manifest
    python download_library.py one "Berakhot"      # a single index by name

Output: library/output/<category>/<title>__<lang>.epub
Cache:  library/cache/index/<title>.json  (resumable)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from html import escape
from pathlib import Path

import requests
from ebooklib import epub

API = "https://www.sefaria.org/api"
USER_AGENT = "kobo-shabbos-library/1.0"

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
OUT = ROOT / "output"
MANIFEST = ROOT / "library_manifest.json"


# ---------------------------------------------------------------------------
# HTTP
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


def fetch_index_bulk(title: str) -> dict:
    """
    One HTTP request returns the entire content of an index (Tanakh book,
    Talmud masechta, Siddur, etc.) plus metadata (sectionNames, addressTypes,
    lengths). Cached to disk per title.

    For complex-schema indexes (Siddur, etc.) the bulk endpoint returns 400.
    Caller should detect that via fetch_index_meta() and use the schema walk.
    """
    p = CACHE / "index" / f"{slug(title)}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))

    print(f"  fetching {title} ...", file=sys.stderr)
    data = http_get_json(f"{API}/texts/{title}",
                         params={"context": 0, "pad": 0, "commentary": 0})
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def fetch_index_meta(title: str) -> dict:
    p = CACHE / "meta" / f"{slug(title)}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    data = http_get_json(f"{API}/index/{title}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def fetch_ref_bulk(ref: str) -> dict:
    """Fetch any ref (leaf in a complex index) via the bulk endpoint."""
    p = CACHE / "ref" / f"{slug(ref)}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    data = http_get_json(f"{API}/texts/{ref}",
                         params={"context": 0, "pad": 0, "commentary": 0})
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def schema_leaves(title: str, schema: dict) -> list[tuple[list[str], dict]]:
    """
    Walk a complex schema and yield (path_titles, leaf_node) for each leaf.
    The path includes the index title at index 0. The leaf ref is
    ", ".join(path).
    """
    out: list[tuple[list[str], dict]] = []

    def walk(node: dict, path: list[str]) -> None:
        children = node.get("nodes")
        if children:
            for child in children:
                t = child.get("title") or child.get("key") or "?"
                walk(child, path + [t])
        else:
            out.append((path, node))

    walk({"nodes": schema.get("nodes", [])}, [title])
    return out


# ---------------------------------------------------------------------------
# Section labels (Genesis 1, Berakhot 2a, ...) derived from bulk response
# ---------------------------------------------------------------------------
def section_labels(data: dict) -> list[str]:
    title = data.get("indexTitle") or data.get("book") or data.get("ref") or ""
    address_types = data.get("addressTypes") or []
    he = data.get("he") or []
    en = data.get("text") or []
    n = max(len(he), len(en))

    if address_types and address_types[0] == "Talmud":
        # Sefaria's array reserves slots 0/1 for the nonexistent daf 1.
        # First real daf (2a) lives at index 2.  daf = (i // 2) + 1
        return [f"{title} {(i // 2) + 1}{'a' if i % 2 == 0 else 'b'}"
                for i in range(n)]
    return [f"{title} {i + 1}" for i in range(n)]


# ---------------------------------------------------------------------------
# Section text -> HTML
# ---------------------------------------------------------------------------
def _flatten(arr) -> list[str]:
    out = []
    if isinstance(arr, list):
        for x in arr:
            out.extend(_flatten(x))
    elif arr is None or arr == "":
        pass
    else:
        out.append(str(arr))
    return out


def section_html(label: str, he_block, en_block, lang: str) -> str:
    he_lines = _flatten(he_block)
    en_lines = _flatten(en_block)
    parts = [f"<h2>{escape(label)}</h2>"]
    if lang in ("he", "both") and he_lines:
        parts.append('<div dir="rtl" lang="he" style="font-size:1.1em">')
        for i, line in enumerate(he_lines, 1):
            parts.append(f"<p><sup>{i}</sup> {line}</p>")
        parts.append("</div>")
    if lang in ("en", "both") and en_lines:
        parts.append('<div dir="ltr" lang="en">')
        for i, line in enumerate(en_lines, 1):
            parts.append(f"<p><sup>{i}</sup> {line}</p>")
        parts.append("</div>")
    if lang == "both" and he_lines and not en_lines:
        parts.append("<p><em>(no English available)</em></p>")
    if not he_lines and not en_lines:
        parts.append("<p><em>(empty section)</em></p>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# EPUB
# ---------------------------------------------------------------------------
def build_epub_from_bulk(title: str, data: dict, lang: str,
                         out_path: Path, *, license_note: str = "") -> None:
    book = epub.EpubBook()
    book.set_identifier(f"kobo-shabbos:{slug(title)}:{lang}")
    book.set_title(title)
    book.set_language("he" if lang == "he" else "en")
    book.add_author("Sefaria community + classic editions (see About)")

    labels = section_labels(data)
    he = data.get("he") or []
    en = data.get("text") or []
    n = len(labels)

    chapters = []
    nonempty = 0
    for i in range(n):
        he_block = he[i] if i < len(he) else []
        en_block = en[i] if i < len(en) else []
        if not _flatten(he_block) and not _flatten(en_block):
            continue
        nonempty += 1
        ch = epub.EpubHtml(
            title=labels[i],
            file_name=f"sec_{i:04d}.xhtml",
            lang="he" if lang == "he" else "en",
        )
        body = section_html(labels[i], he_block, en_block, lang)
        ch.content = (
            f'<html xmlns="http://www.w3.org/1999/xhtml"><head>'
            f'<title>{escape(labels[i])}</title></head><body>{body}</body></html>'
        )
        book.add_item(ch)
        chapters.append(ch)

    about = epub.EpubHtml(title="About", file_name="about.xhtml")
    about.content = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>About</title></head><body>'
        f"<h1>{escape(title)}</h1>"
        f"<p>Sections included: {nonempty} of {n}.</p>"
        f"<p>Source: <a href=\"https://www.sefaria.org\">Sefaria</a> public API.</p>"
        f"<p>{escape(license_note) or 'See sefaria.org/terms for licensing.'}</p>"
        "</body></html>"
    )
    book.add_item(about)

    book.toc = tuple(chapters)
    book.spine = ["nav", about] + chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book)
    print(f"  -> {out_path}  ({nonempty} sections)", file=sys.stderr)


def build_epub_from_complex(title: str, meta: dict, lang: str,
                            out_path: Path, *,
                            license_note: str = "") -> None:
    book = epub.EpubBook()
    book.set_identifier(f"kobo-shabbos:{slug(title)}:{lang}")
    book.set_title(title)
    book.set_language("he" if lang == "he" else "en")
    book.add_author("Sefaria community")

    leaves = schema_leaves(title, meta.get("schema", {}))
    print(f"  {len(leaves)} leaf sections", file=sys.stderr)

    chapters: list[epub.EpubHtml] = []
    # toc tree: list of (Section, [chapters]) by top-level
    toc_groups: dict[str, list[epub.EpubHtml]] = {}

    for idx, (path, _node) in enumerate(leaves):
        ref = ", ".join(path)
        if (idx + 1) % 50 == 0 or idx == 0 or idx == len(leaves) - 1:
            print(f"    [{idx+1}/{len(leaves)}] {ref}", file=sys.stderr)
        try:
            data = fetch_ref_bulk(ref)
        except Exception as e:
            print(f"    skipping {ref}: {e}", file=sys.stderr)
            continue
        he = data.get("he") or []
        en = data.get("text") or []
        if not _flatten(he) and not _flatten(en):
            continue
        leaf_label = " / ".join(path[1:])
        ch = epub.EpubHtml(
            title=leaf_label,
            file_name=f"sec_{idx:04d}.xhtml",
            lang="he" if lang == "he" else "en",
        )
        body = section_html(leaf_label, he, en, lang)
        ch.content = (
            f'<html xmlns="http://www.w3.org/1999/xhtml"><head>'
            f'<title>{escape(leaf_label)}</title></head><body>{body}</body></html>'
        )
        book.add_item(ch)
        chapters.append(ch)
        toc_groups.setdefault(path[1] if len(path) > 1 else "Other", []).append(ch)

    about = epub.EpubHtml(title="About", file_name="about.xhtml")
    about.content = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>About</title></head><body>'
        f"<h1>{escape(title)}</h1>"
        f"<p>Sections included: {len(chapters)} of {len(leaves)}.</p>"
        f"<p>Source: <a href=\"https://www.sefaria.org\">Sefaria</a> public API.</p>"
        f"<p>{escape(license_note) or 'See sefaria.org/terms for licensing.'}</p>"
        "</body></html>"
    )
    book.add_item(about)

    # Hierarchical TOC: one Section per top-level group
    book.toc = tuple(
        (epub.Section(group_name), tuple(group_chapters))
        for group_name, group_chapters in toc_groups.items()
    )
    book.spine = ["nav", about] + chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book)
    print(f"  -> {out_path}  ({len(chapters)} sections, "
          f"{len(toc_groups)} top-level groups)", file=sys.stderr)


# ---------------------------------------------------------------------------
# Build flow
# ---------------------------------------------------------------------------
def build_one(title: str, *, category: str, lang: str = "both") -> None:
    print(f"== {title} ({lang}) ==", file=sys.stderr)
    out = OUT / category / f"{slug(title)}__{lang}.epub"

    # Probe the index metadata first; complex-schema indexes (Siddur etc.)
    # can't be fetched in one bulk call.
    meta = fetch_index_meta(title)
    is_complex = bool(meta.get("schema", {}).get("nodes"))

    if is_complex:
        license_note = "Liturgy text; see sefaria.org/terms for licensing."
        build_epub_from_complex(title, meta, lang, out,
                                license_note=license_note)
        return

    data = fetch_index_bulk(title)
    if "Talmud" in (data.get("addressTypes") or []):
        license_note = ("English: William Davidson Talmud, CC-BY-NC. "
                        "Hebrew: Vilna edition, public domain.")
    else:
        license_note = "Multiple licenses; see sefaria.org/terms."
    build_epub_from_bulk(title, data, lang, out, license_note=license_note)


def build_category(category: str, titles: list, lang: str) -> None:
    for t in titles:
        if isinstance(t, dict):
            t = t.get("sefaria_index") or t.get("title")
        try:
            build_one(t, category=category, lang=lang)
        except Exception as e:
            print(f"!! {t} failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["tanakh", "shas", "siddur", "all", "one"])
    ap.add_argument("title", nargs="?",
                    help="(for 'one' command) Sefaria index title")
    ap.add_argument("--lang", choices=["he", "en", "both"], default="both")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    CACHE.mkdir(exist_ok=True)

    if args.command == "tanakh":
        build_category("tanakh", manifest["tanakh"], args.lang)
    elif args.command == "shas":
        build_category("shas_bavli", manifest["shas_bavli"], args.lang)
    elif args.command == "siddur":
        build_category("siddur", manifest["siddur"], args.lang)
    elif args.command == "all":
        build_category("tanakh", manifest["tanakh"], args.lang)
        build_category("siddur", manifest["siddur"], args.lang)
        build_category("shas_bavli", manifest["shas_bavli"], args.lang)
    elif args.command == "one":
        if not args.title:
            ap.error("'one' requires a title")
        build_one(args.title, category="custom", lang=args.lang)

    print("done.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
