#!/usr/bin/env python3
"""Generate an independent full-text RSS feed for a future Dzen site connection.

Published iipike.ru news.json is the allowlist. The feed's full article HTML
comes from approved *original Dzen* Markdown, NOT site HTML with site links.
No Dzen API, browser, secrets or posting calls. This module can be used by
the existing site-first publisher in the same atomic reviewed commit.
"""
import argparse
import datetime as dt
from email.utils import format_datetime
from html import escape
import json
import mimetypes
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.site_rich_text import markdown_to_blocks, render_blocks

BASE = "https://iipike.ru"
FILE = "dzen-rss.xml"
CONFIG = Path("data/dzen_rss_export.json")
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
MAX_BYTES = 10_000_000
ALLOWED_COVERS = {".png": "image/png", ".jpg": "image/jpeg",
                  ".jpeg": "image/jpeg", ".webp": "image/webp"}
ARTICLE_URL = re.compile(r"articles/([a-z0-9]+(?:-[a-z0-9]+)*)/\Z")
ASSET_PATH = re.compile(r"assets/editorial/[a-zA-Z0-9_-]+\.(?:webp|png|jpg|jpeg)\Z")


def utc(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ValueError("RSS timestamp must be an exact ISO UTC second")
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def read_settings(root):
    # Minimal isolated publisher test roots do not carry the deployment config.
    # The only safe fallback is standby, never an implicit active cutover.
    path = root / CONFIG
    data = (json.loads(path.read_text(encoding="utf-8")) if path.is_file()
            else {"schema_version": 1, "mode": "standby",
                  "cutover_at_utc": None, "max_items": 40})
    if not isinstance(data, dict) or set(data) != {
            "schema_version", "mode", "cutover_at_utc", "max_items"}:
        raise ValueError("Invalid RSS export settings schema")
    if data["schema_version"] != 1 or data["mode"] not in ("standby", "active"):
        raise ValueError("Unknown RSS export mode")
    if type(data["max_items"]) is not int or not 1 <= data["max_items"] <= 100:
        raise ValueError("RSS export max_items must be 1..100")
    if data["mode"] == "active":
        utc(data["cutover_at_utc"])
    elif data["cutover_at_utc"] is not None:
        raise ValueError("Standby RSS must not declare a misleading cutover")
    return data


def approved_dzen_source(root, row, *, staged=None):
    """Only completed site-first publications with approved original Markdown."""
    if not isinstance(row, dict):
        return None
    rel = row.get("url")
    matched = ARTICLE_URL.fullmatch(rel) if isinstance(rel, str) else None
    if not matched or row.get("id") != matched[1]:
        return None
    if row.get("dzen_id") or row.get("site_first_dzen_id"):
        # Historical Dzen copies and known manually mirrored Dzen items
        # must never be presented as new imports.
        return None
    stamp = row.get("published_at_utc")
    try:
        when = utc(stamp)
    except ValueError:
        return None
    slug = matched[1]
    source_path = root / "content" / "approved" / (slug + ".json")
    is_staged = staged is not None and staged.get("slug") == slug
    if not is_staged and (not source_path.is_file()
                          or not (root / rel / "index.html").is_file()):
        return None
    data = staged if is_staged else json.loads(source_path.read_text(encoding="utf-8"))
    if (data.get("slug") != slug or data.get("status") != "approved"
            or not isinstance(data.get("approved_by"), str) or not data["approved_by"]
            or data.get("title") != row.get("title")
            or data.get("published_at_utc") != stamp
            or not isinstance(data.get("article_markdown"), str)):
        return None
    # This is exact parity with the approved Dzen source, not a second rewrite.
    blocks = markdown_to_blocks(data["article_markdown"])
    if data.get("paragraphs") != blocks:
        raise ValueError("RSS source differs from editor-approved Markdown: " + slug)
    title = row["title"]
    if not 1 <= len(title) <= 200 or not isinstance(row.get("summary"), str):
        return None
    cover = row.get("cover", "")
    if not isinstance(cover, str) or not ASSET_PATH.fullmatch(cover):
        # Content still publishes on site; a malformed cover is not silently
        # exported to Dzen. Keep ordinary site publication unaffected.
        return None
    if data.get("cover") != cover:
        return None
    cover_path = root / cover
    if not cover_path.is_file() or cover_path.is_symlink():
        return None
    if cover_path.stat().st_size > 16 * 1024 * 1024:
        return None
    return when, data, blocks, cover_path


def cdata(text):
    # Well-formed even if editor text contains a literal CDATA terminator.
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def plain_html(blocks):
    """Only safe editorial HTML; no site-only crosslink transformation."""
    html = render_blocks(blocks)
    html = re.sub(r' class="[^"]*"', "", html)
    html = html.replace(' target="_blank" rel="noopener noreferrer"', "")
    return html


def render(root, records, *, staged=None, settings=None):
    """Build deterministic RSS 2.0 for published site-first approved stories."""
    settings = settings or read_settings(root)
    if not isinstance(records, list):
        raise ValueError("RSS records must be a list")
    cutover = (utc(settings["cutover_at_utc"])
               if settings["mode"] == "active" else None)
    candidates = []
    seen = set()
    for row in records:
        sid = row.get("id") if isinstance(row, dict) else None
        if sid in seen:
            raise ValueError("Duplicate published story ID in Dzen export index")
        seen.add(sid)
        result = approved_dzen_source(root, row, staged=staged)
        if result is None:
            continue
        when, data, blocks, cover_path = result
        if cutover and when < cutover:
            continue
        candidates.append((when, row["id"], row, blocks, cover_path))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)

    items = []
    for when, sid, row, blocks, cover_path in candidates[:settings["max_items"]]:
        url = BASE + "/" + row["url"]
        cover = BASE + "/" + row["cover"]
        length = cover_path.stat().st_size
        mime = ALLOWED_COVERS[cover_path.suffix.lower()]
        full = ('<p><img src="' + escape(cover, quote=True)
                + '" alt="' + escape(row["title"], quote=True)
                + '"></p>\n' + plain_html(blocks))
        items.append(
            "<item>"
            "<title>" + escape(row["title"]) + "</title>"
            "<link>" + escape(url) + "</link>"
            '<guid isPermaLink="true">' + escape(url) + "</guid>"
            "<pubDate>" + format_datetime(when, usegmt=True) + "</pubDate>"
            "<description>" + escape(row["summary"]) + "</description>"
            '<enclosure url="' + escape(cover, quote=True)
            + '" length="' + str(length) + '" type="' + mime + '"/>'
            "<content:encoded>" + cdata(full) + "</content:encoded>"
            "</item>"
        )
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:content="' + CONTENT_NS + '">'
        "<channel><title>Хроники Пикирующего ИИ</title>"
        "<link>" + BASE + "/</link>"
        "<description>Полные утверждённые статьи ХПИИ для RSS-трансляции в Дзен</description>"
        "<language>ru-RU</language>"
        + "".join(items) + "</channel></rss>\n"
    )
    if len(feed.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Dzen RSS exceeds 10 MB limit")
    # Always parse the actual output rather than trusting string assembly.
    parsed = ET.fromstring(feed)
    exported = parsed.findall("./channel/item")
    if len(exported) != len(items):
        raise ValueError("RSS items count mismatch")
    for item in exported:
        if not item.findtext("{" + CONTENT_NS + "}encoded") or not item.findtext("pubDate"):
            raise ValueError("Full article or RFC-822 pubDate missing")
    return feed


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check", action="store_true", help="Check committed feed only")
    p.add_argument("--output", type=Path, default=ROOT / FILE)
    args = p.parse_args()
    records = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
    expected = render(ROOT, records)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != expected:
            p.exit(1, "Dzen RSS is stale: regenerate from approved site publications\n")
        print("Dzen RSS matches published approved site-first source")
    else:
        args.output.write_text(expected, encoding="utf-8")
        print("Dzen RSS ready:", args.output, "bytes:", len(expected.encode("utf-8")))


if __name__ == "__main__":
    main()
