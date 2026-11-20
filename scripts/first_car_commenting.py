#!/usr/bin/env python3
"""Prepare Dzen replies in the existing commenting batch. Never post them."""
from __future__ import annotations

import argparse
import datetime as dt
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from scripts import commenting_queue as cq

DAY = dt.timedelta(hours=24)
RETRY = dt.timedelta(hours=6)


class TextAccessStopped(Exception):
    """An explicit access restriction requires review before trying again."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TextAccessStopped("Redirect on Dzen article")


class DzenPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "link" and values.get("rel") == "canonical":
            self.urls.append(values.get("href"))
        if tag == "meta" and values.get("property") == "og:url":
            self.urls.append(values.get("content"))


def read_dzen_text(url, *, opener=None):
    if not cq.dzen_url(url):
        raise ValueError("Invalid Dzen article URL")
    opener = opener or urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, headers={
        "User-Agent": "HPII-CommentingReader/1.0 (+https://iipike.ru)", "Accept": "text/html",
    })
    try:
        with opener.open(request, timeout=12) as response:
            if response.geturl() != url:
                raise TextAccessStopped("Unexpected Dzen article redirect")
            if response.headers.get_content_type() != "text/html":
                raise ValueError("Expected a public Dzen article page")
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("Dzen article response too large")
            page = raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        if error.code in {401, 403, 429}:
            raise TextAccessStopped(f"Dzen article HTTP {error.code}") from None
        raise
    parser = DzenPage()
    parser.feed(page)
    urls = {x.split("?", 1)[0] for x in parser.urls if isinstance(x, str)}
    if urls != {url}:
        raise ValueError("Dzen article identity is not verified")
    # Use the same article-body extraction and minimum text requirement as for RSS publishers.
    return cq.article_text(page)[0]


def prepare(discovery, previous, media, config, now, *, allowed=False, api_key="", reader=read_dzen_text):
    previous = previous if previous.get("schema_version") == 1 else {}
    existing = {x["url"]: x for x in previous.get("items", [])}
    items = {}
    for article in discovery.get("articles", []):
        url = cq.dzen_url(article.get("url"))
        published = cq.date(article.get("published_at"))
        title = article.get("title")
        if (not url or not published or not 0 <= (now - published).total_seconds() <= DAY.total_seconds()
                or article.get("source") != "dzen_launcher_more" or not isinstance(title, str) or not title.strip()):
            continue
        items[url] = dict(existing.get(url) or {
            "id": "first-car:" + url.rsplit("/", 1)[-1], "url": url,
            "published_at": article["published_at"], "title": title, "status": "pending", "attempts": 0,
        })
    queue = {"schema_version": 1, "items": list(items.values()), "text_blocked": previous.get("text_blocked")}
    pending = [row for row in items.values() if row["status"] in {"pending", "needs_text", "read_error", "generation_error"}]
    if not allowed or queue["text_blocked"] or discovery.get("blocked"):
        for row in pending:
            row["status"] = "needs_text"
        return queue, None
    today = now.astimezone(dt.timezone(dt.timedelta(hours=5))).date().isoformat()
    usage = media.get("usage", {})
    if not api_key or (usage.get("date") == today and usage.get("attempted", 0) >= config["max_per_day"]):
        return queue, None
    eligible = [row for row in pending if row["attempts"] < 2 and (
        not row.get("last_attempt_at") or now - cq.date(row["last_attempt_at"]) >= RETRY
    )]
    if not eligible:
        return queue, None
    row = max(eligible, key=lambda item: item["published_at"])
    try:
        text = reader(row["url"])
        if not isinstance(text, str) or not 350 <= len(text) <= cq.MAX_ARTICLE_CHARS:
            raise ValueError("Dzen article body is unavailable")
    except Exception as error:
        row.update(status="read_error", attempts=row["attempts"] + 1, last_attempt_at=cq.stamp(now))
        if isinstance(error, TextAccessStopped):
            queue["text_blocked"] = {"at": cq.stamp(now), "reason": str(error)}
        return queue, None
    return queue, {"item": row, "article_text": text}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("state", "output", "discovery", "drafts-state", "drafts-output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    config = cq.load_config(cq.ROOT / "data/commenting_sources.json")
    media = json.loads(args.state.read_text(encoding="utf-8"))
    try:
        discovery = json.loads(args.discovery.read_text(encoding="utf-8"))
        old_drafts = json.loads(args.drafts_state.read_text(encoding="utf-8"))
        drafts, first_car = prepare(discovery, old_drafts, media, config, now,
                                    allowed=os.environ.get("FIRST_CAR_ARTICLE_TEXT") == "enabled", api_key=api_key)
    except Exception:
        # An optional Dzen input must never prevent the normal publisher pass.
        print("First Car draft preparation unavailable")
        drafts, first_car = None, None
    result = cq.build_queue(config, media, now, api_key=api_key, first_car=first_car)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if drafts is not None:
        args.drafts_output.write_text(json.dumps(drafts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
