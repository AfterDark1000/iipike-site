#!/usr/bin/env python3
"""Read-only verification of the HPI primary-source catalog.

No paid API, model generation or publication. The diagnostic tests whether
the actual GitHub runner can fetch RSS/Atom and parse recent entries.
"""
import concurrent.futures
import datetime as dt
import json
import pathlib
import sys
import urllib.error
import xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import editorial_draft as ed
import editorial_sources as sources


def check_feed(entry, now):
    publisher, url, _ = entry
    try:
        raw = ed.get_bytes(url)
        root = ET.fromstring(raw)
        entries = [item for item in root.iter() if ed.tag(item) in ("item", "entry")]
        recent = ed.parse_feed(raw, publisher, now)
        if publisher in {"Microsoft", "NVIDIA", "NVIDIA Developers",
                         "Amazon AWS ML", "Cloudflare", "Google Developers",
                         "Google Research"}:
            recent = [x for x in recent if sources.relevant_headline(x["headline"])]
        return {"publisher": publisher, "readable": True, "feed_entries": len(entries),
                "recent_relevant": len(recent)}
    except (ValueError, RuntimeError, ET.ParseError, urllib.error.URLError,
            TimeoutError) as error:
        code = str(error.code) if isinstance(error, urllib.error.HTTPError) else type(error).__name__
        return {"publisher": publisher, "readable": False, "error": code}


def main():
    now = dt.datetime.now(dt.timezone.utc)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lambda entry: check_feed(entry, now), sources.SOURCES))
    for row in rows:
        print("SOURCE CHECK " + json.dumps(row, ensure_ascii=False), flush=True)
    readable = sum(int(x["readable"]) for x in rows)
    useful = sum(int(x.get("recent_relevant", 0)) for x in rows)
    print(f"TOTAL: configured={len(rows)}, readable={readable}, relevant_in_72h={useful}",
          flush=True)
    try:
        found = sources.discover_hn(now, max_age_hours=ed.MAX_AGE_HOURS)
        print("HN DISCOVERY: first-party candidate links=" + str(len(found)), flush=True)
    except (ValueError, RuntimeError, urllib.error.URLError) as error:
        print("HN DISCOVERY ERROR: " + type(error).__name__, flush=True)
    if readable == 0:
        raise RuntimeError("No RSS feeds readable: discovery network may be blocked")


if __name__ == "__main__":
    main()
