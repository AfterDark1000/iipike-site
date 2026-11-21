#!/usr/bin/env python3
"""Generate inert VK RSS comparison fixtures without touching the live feed.

All variants reuse ONE already published article, its original GUID and pubDate.
They are NOT automatically subscribed to by VK, so this cannot test VK's
external importer unless a human explicitly changes the subscription URL.
"""
import argparse
from html import escape
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "vk-rss.xml"
DEST = ROOT / "experiments" / "vk-rss-lab"
SLUG = "meta-muse-chrome-login-20261120"
ART_URL = "https://iipike.ru/articles/" + SLUG + "/"

def fixture(item, *, label, media=False):
    media_ns = ' xmlns:media="http://search.yahoo.com/mrss/"' if media else ""
    channel = ("<channel><title>ХПИИ — ОТКЛЮЧЁННЫЙ RSS-ЭКСПЕРИМЕНТ: "
               + escape(label) + "</title><link>https://iipike.ru/</link>"
               "<description>Изолированная диагностика, не подключено к ВКонтакте</description>"
               "<language>ru-RU</language>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0"' + media_ns + '>'
            + channel + item + '</channel></rss>\n')

def render(source):
    # Preserve CDATA, original image, GUID and timestamp byte-for-byte.
    pattern = r"<item><title>[^<]*</title><link>" + re.escape(ART_URL) + r"</link>[\s\S]*?</item>"
    matches = re.findall(pattern, source)
    if len(matches) != 1:
        raise ValueError("Expected exactly one already-published Muse item")
    original = matches[0]
    ET.fromstring(fixture(original, label="контроль"))
    image_match = re.search(r'<enclosure url="([^"]+)" type="image/jpeg" length="([0-9]+)"/>', original)
    if not image_match:
        raise ValueError("Missing prepared JPEG enclosure")
    img_url = image_match[1]
    if img_url != "https://iipike.ru/assets/vk/" + SLUG + ".jpg":
        raise ValueError("Unexpected image URL")
    media_tag = (f'<media:content url="{escape(img_url)}" medium="image" '
                 f'type="image/jpeg" width="1280" height="720"/>'
                 f'<media:thumbnail url="{escape(img_url)}" width="1280" height="720"/>')
    with_media = original.replace("</item>", media_tag + "</item>")
    # Diagnostic only: test whether presence of <link> drives preview cards.
    no_link = original.replace("<link>" + ART_URL + "</link>", "")
    no_link = no_link.replace('guid isPermaLink="true"', 'guid isPermaLink="false"')
    if no_link == original:
        raise ValueError("Failed to remove link")
    # A separate experiment checks whether an ordinary text URL also
    # forces the preview even when the item's <link> is absent.
    link_in_text = no_link.replace(
        "</p>]]></description>",
        "</p><p>Читать на сайте: " + escape(ART_URL) + "</p>]]></description>")
    if link_in_text == no_link:
        raise ValueError("Could not append text URL")
    variants = {
        "01-control.xml": fixture(original, label="контроль, оригинальная запись"),
        "02-media-image.xml": fixture(with_media, label="медиа-вложение JPEG", media=True),
        "03-photo-only-diagnostic.xml": fixture(no_link, label="без link, без ссылки в тексте"),
        "04-text-url-diagnostic.xml": fixture(link_in_text, label="ссылка только в тексте"),
    }
    for name, document in variants.items():
        root = ET.fromstring(document)
        items = root.findall("./channel/item")
        if len(items) != 1:
            raise ValueError("Test fixture must contain exactly one item")
        item = items[0]
        if item.findtext("guid") != ART_URL:
            raise ValueError("Original GUID changed")
        if item.findtext("pubDate") != "Sat, 21 Nov 2026 17:45:41 GMT":
            raise ValueError("Original pubDate changed")
        if len(item.findall("enclosure")) != 1:
            raise ValueError("JPEG enclosure changed")
        if img_url not in item.findtext("description", ""):
            raise ValueError("First image was removed from description")
    return variants

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--write", action="store_true", help="Create inert experimental files")
    p.add_argument("--check", action="store_true", help="Verify committed fixtures")
    args = p.parse_args()
    if args.write == args.check:
        p.error("Choose exactly one of --write or --check")
    variants = render(SOURCE.read_text(encoding="utf-8"))
    if args.write:
        DEST.mkdir(parents=True, exist_ok=True)
    for name, value in variants.items():
        output = DEST / name
        if args.write:
            output.write_text(value, encoding="utf-8")
        elif not output.is_file() or output.read_text(encoding="utf-8") != value:
            raise ValueError("Fixture outdated: " + str(output))
    print("VK RSS LAB:", len(variants), "inert fixtures verified; live feed unchanged")

if __name__ == "__main__":
    main()
