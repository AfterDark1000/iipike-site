#!/usr/bin/env python3
"""Generate an opt-in image-first RSS feed for VK from *published* site news.

Never posts to VK, calls APIs, or touches feed.xml/dzen-rss.xml.
New images are deterministic JPEG copies of approved local covers. The feed
remains empty until an explicit cutover is configured after a VK pilot.
"""
import argparse
import datetime as dt
from email.utils import format_datetime
from html import escape
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://iipike.ru"
FILE = "vk-rss.xml"
CONFIG = "data/vk_rss_export.json"
MAX_BYTES = 2_000_000
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
VALID_COVER = re.compile(r"assets/editorial/([a-z0-9]+(?:-[a-z0-9]+)*)\.(?:webp|jpg|jpeg|png)\Z")


def timestamp(value):
    if not isinstance(value, str) or not UTC.fullmatch(value):
        raise ValueError("VK RSS cutover/pubDate needs exact ISO-8601 UTC seconds")
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def settings_from(root):
    path = root / CONFIG
    data = (json.loads(path.read_text(encoding="utf-8")) if path.is_file()
            else {"schema_version": 1, "mode": "standby",
                  "cutover_at_utc": None, "max_items": 12})
    if (not isinstance(data, dict) or set(data) !=
            {"schema_version", "mode", "cutover_at_utc", "max_items"}):
        raise ValueError("Invalid VK RSS settings schema")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unknown VK RSS settings schema version")
    if data["mode"] not in ("standby", "pilot", "active"):
        raise ValueError("Unknown VK RSS mode")
    if type(data["max_items"]) is not int or not 1 <= data["max_items"] <= 20:
        raise ValueError("VK RSS max_items must be 1..20")
    if data["mode"] in ("pilot", "active"):
        timestamp(data["cutover_at_utc"])
        if data["mode"] == "pilot" and data["max_items"] != 1:
            raise ValueError("VK RSS pilot must be limited to exactly one article")
    elif data["cutover_at_utc"] is not None:
        raise ValueError("Standby VK RSS must not contain a cutover")
    return data


def eligible(root, rows, settings):
    if not isinstance(rows, list):
        raise ValueError("Published news index is not a list")
    if settings["mode"] == "standby":
        return []
    cutover = timestamp(settings["cutover_at_utc"])
    candidates = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        slug = row.get("id")
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            continue
        if slug in seen:
            raise ValueError("Duplicate published article ID in VK RSS input: " + slug)
        seen.add(slug)
        if row.get("dzen_id") or row.get("site_first_dzen_id"):
            continue
        if row.get("url") != f"articles/{slug}/":
            continue
        try:
            when = timestamp(row.get("published_at_utc"))
        except ValueError:
            continue
        if when < cutover:
            continue
        # Only the VK feed sees VK-specific editorial copy. Historical rows
        # (and editors who omit those fields) keep their exact previous text.
        title = row.get("vk_title", row.get("title"))
        summary = row.get("vk_summary", row.get("summary"))
        if (not isinstance(title, str) or not 1 <= len(title) <= 200 or
                not isinstance(summary, str) or not 1 <= len(summary) <= 2000):
            continue
        cover = row.get("cover")
        match = VALID_COVER.fullmatch(cover) if isinstance(cover, str) else None
        if not match or match[1] != slug:
            continue
        cover_path = root / cover
        article_path = root / row["url"] / "index.html"
        if (not article_path.is_file() or article_path.is_symlink() or
                not cover_path.is_file() or cover_path.is_symlink() or
                cover_path.stat().st_size > 16 * 1024 * 1024):
            continue
        candidates.append((when, slug, row, cover_path))
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=settings["mode"] != "pilot")
    # Pilot freezes on the FIRST eligible published story, even when more
    # stories arrive. Do not silently import the later ones before review.
    return candidates[:1 if settings["mode"] == "pilot" else settings["max_items"]]


def jpeg_bytes(cover_path):
    with Image.open(cover_path) as source:
        frame = ImageOps.exif_transpose(source).convert("RGB")
        if frame.width < 320 or frame.height < 160:
            raise ValueError("VK cover too small: " + str(cover_path))
        if not 0.5 <= frame.width / frame.height <= 2.0:
            raise ValueError("VK cover aspect ratio out of range: " + str(cover_path))
        frame.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        frame.save(buffer, format="JPEG", quality=88, optimize=True, progressive=False)
        return buffer.getvalue()


def cdata(value):
    return "<![CDATA[" + value.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def render(root, rows, *, settings=None):
    """Return XML text and JPEG assets without mutating anything on disk."""
    cfg = settings if settings is not None else settings_from(root)
    if cfg["mode"] != "standby":
        timestamp(cfg["cutover_at_utc"])
    images = {}
    items = []
    for when, slug, row, cover_path in eligible(root, rows, cfg):
        jpg = jpeg_bytes(cover_path)
        relative = f"assets/vk/{slug}.jpg"
        images[root / relative] = jpg
        img_url = BASE + "/" + relative
        url = BASE + "/" + row["url"]
        title = row.get("vk_title", row["title"])
        summary = row.get("vk_summary", row["summary"])
        description = ('<p><img src="' + escape(img_url, quote=True)
                       + '" alt="' + escape(title, quote=True)
                       + '"></p><p>' + escape(summary) + '</p>')
        items.append(
            "<item><title>" + escape(title) + "</title>"
            "<link>" + escape(url) + "</link>"
            '<guid isPermaLink="true">' + escape(url) + "</guid>"
            "<pubDate>" + format_datetime(when, usegmt=True) + "</pubDate>"
            "<description>" + cdata(description) + "</description>"
            '<enclosure url="' + escape(img_url, quote=True)
            + '" type="image/jpeg" length="' + str(len(jpg)) + '"/>'
            "</item>"
        )
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<rss version="2.0"><channel>'
           '<title>Хроники Пикирующего ИИ — ВКонтакте</title>'
           '<link>' + BASE + '/</link>'
           '<description>Короткие анонсы опубликованных новостей ХПИИ с обложками</description>'
           '<language>ru-RU</language>' + ''.join(items) + '</channel></rss>\n')
    if len(xml.encode("utf-8")) > MAX_BYTES:
        raise ValueError("VK RSS exceeds size budget")
    parsed = ET.fromstring(xml)
    exported = parsed.findall("./channel/item")
    if len(exported) != len(items):
        raise ValueError("VK RSS item count mismatch")
    for item in exported:
        desc = item.findtext("description", "")
        image = item.find("enclosure")
        if not desc.startswith("<p><img src=") or image is None or image.get("type") != "image/jpeg":
            raise ValueError("VK RSS item missing an image or preview")
    return xml, images


def export(root, *, check=False):
    rows = json.loads((root / "news.json").read_text(encoding="utf-8"))
    xml, images = render(root, rows)
    path = root / FILE
    if check:
        if not path.is_file() or path.read_text(encoding="utf-8") != xml:
            raise ValueError("VK RSS feed is stale")
        for target, contents in images.items():
            if not target.is_file() or target.read_bytes() != contents:
                raise ValueError("VK RSS image missing/stale: " + str(target))
        return len(images)
    for target, contents in images.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != contents:
            target.write_bytes(contents)
    if not path.exists() or path.read_text(encoding="utf-8") != xml:
        path.write_text(xml, encoding="utf-8")
    return len(images)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Read-only validation")
    args = parser.parse_args()
    try:
        count = export(ROOT, check=args.check)
    except (ValueError, OSError) as exc:
        parser.exit(1, "VK RSS: " + str(exc) + "\n")
    print("VK RSS", "validated" if args.check else "generated",
          "JPEG covers:", count)


if __name__ == "__main__":
    main()
