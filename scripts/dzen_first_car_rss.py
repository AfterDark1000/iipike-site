"""Read saved publisher feeds as hints for the Dzen queue, without network access."""

import argparse
import json
import re
from contextlib import closing
from datetime import UTC
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

from dzen_first_car import canonical, connect, iso, timestamp
from dzen_stage_a5_audit import SLUG, topic_basis

MAX_FEED_BYTES = 4_000_000
MAX_AGE_SECONDS = 3600
PUBLISHER_AI = re.compile(r"\b(?:Apple Intelligence|Galaxy AI|Алиса AI|GitHub Copilot)\b", re.IGNORECASE)


def children(entry):
    return {child.tag.rsplit("}", 1)[-1]: child for child in entry}


def feed_timestamp(value):
    try:
        return timestamp(value)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            return int(parsed.astimezone(UTC).timestamp()) if parsed.tzinfo else None
        except (ValueError, TypeError, OverflowError):
            return None


def alternate_urls(entry):
    for child in entry:
        if child.tag.rsplit("}", 1)[-1] == "link" and child.get("rel", "alternate") == "alternate":
            yield (child.get("href") or child.text or "").strip()


def explicit_dzen_url(urls):
    direct = set()
    for url in urls:
        try:
            direct.add(canonical(url))
        except ValueError:
            continue
    return direct.pop() if len(direct) == 1 else None


def publisher_entries(xml, as_of):
    if len(xml) > MAX_FEED_BYTES or b"<!DOCTYPE" in xml.upper():
        raise ValueError("Feed size or document type is unsupported")
    root = ElementTree.fromstring(xml)
    for entry in root.iter():
        if entry.tag.rsplit("}", 1)[-1] not in {"item", "entry"}:
            continue
        data = children(entry)
        text = {key: element.text or "" for key, element in data.items()}
        title = text.get("title", "").strip()
        summary = unescape(re.sub(r"<[^>]+>", " ", (text.get("description") or text.get("summary") or "")[:1000]))
        if not (topic_basis(title, summary) or PUBLISHER_AI.search(title)):
            continue
        published = feed_timestamp(text.get("pubDate") or text.get("published") or "")
        if published is None or not 0 <= as_of - published <= MAX_AGE_SECONDS:
            continue
        urls = list(alternate_urls(entry))
        url = next(iter(urls), "")
        address = urlsplit(url)
        guid = text.get("guid") or text.get("id") or url
        if guid and address.scheme == "https" and address.hostname and not address.username:
            item = {"title": title, "publisher_url": url, "publisher_published_at": iso(published)}
            if dzen_url := explicit_dzen_url(urls):
                item["dzen_url"] = dzen_url
            yield guid, item


def hints(db, channel, feed_url, xml, as_of):
    address = urlsplit(feed_url)
    if not SLUG.fullmatch(channel) or address.scheme != "https" or not address.hostname or address.username:
        raise ValueError("Expected a channel and a public HTTPS feed")
    with db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS rss_seen(
                   channel TEXT NOT NULL, feed TEXT NOT NULL, item TEXT NOT NULL,
                   PRIMARY KEY(channel, feed, item))""")
        new = []
        for guid, item in publisher_entries(xml, as_of):
            seen = sha256(guid.encode("utf-8")).hexdigest()
            if db.execute("INSERT OR IGNORE INTO rss_seen VALUES (?, ?, ?)", (channel, feed_url, seen)).rowcount:
                new.append(item)
    return {"channel": channel, "feed_url": feed_url, "observed_at": iso(as_of),
            "request_hint": bool(new), "confirmed_on_dzen": False, "new_publisher_items": new}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--feed-url", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("saved_feed", type=Path)
    args = parser.parse_args()
    try:
        with args.saved_feed.open("rb") as stream, closing(connect(args.db)) as db:
            result = hints(db, args.channel, args.feed_url, stream.read(MAX_FEED_BYTES + 1), timestamp(args.as_of))
    except (OSError, ValueError, ElementTree.ParseError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
