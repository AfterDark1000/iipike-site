#!/usr/bin/env python3
"""Prepare Dzen replies in the existing commenting batch. Never post them."""
from __future__ import annotations

import argparse
import datetime as dt
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import signal
import urllib.error
import urllib.request

from scripts import commenting_queue as cq

DAY = dt.timedelta(hours=24)
RETRY = dt.timedelta(hours=6)
PUBLIC_FIELDS = {"id", "url", "title", "published_at", "status", "attempts", "last_attempt_at",
                 "generated_at", "comment", "fact_review"}


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


def prepare(discovery, previous, media, config, now, *, allowed=False, api_key="", reader=read_dzen_text,
            submitted=None):
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
            "published_at": article["published_at"], "title": title, "status": "needs_text", "attempts": 0,
        })
    queue = {"schema_version": 1, "items": list(items.values()), "text_blocked": previous.get("text_blocked")}
    pending = [row for row in items.values() if row["status"] in {"pending", "needs_text", "read_error", "generation_error"}]
    texts = {}
    for row in pending:
        text = (submitted or {}).get(row["url"])
        if isinstance(text, str) and 350 <= len(text.strip()) <= cq.MAX_ARTICLE_CHARS:
            texts[row["url"]] = text.strip()
            if row["status"] == "read_error":
                # A failed automatic read consumed no Gemini attempt.
                row["attempts"] = 0
                row.pop("last_attempt_at", None)
            if row["status"] != "generation_error":
                row["status"] = "pending"
        elif row["status"] == "pending":
            row["status"] = "needs_text"
    auto_read = allowed and not queue["text_blocked"] and not discovery.get("blocked")
    today = now.astimezone(dt.timezone(dt.timedelta(hours=5))).date().isoformat()
    usage = media.get("usage", {})
    if not api_key or (usage.get("date") == today and usage.get("attempted", 0) >= config["max_per_day"]):
        return queue, None
    eligible = [row for row in pending if (row["url"] in texts or auto_read) and row["attempts"] < 2 and (
        not row.get("last_attempt_at") or now - cq.date(row["last_attempt_at"]) >= RETRY
    )]
    if not eligible:
        return queue, None
    row = max(eligible, key=lambda item: (item["url"] in texts, cq.date(item["published_at"])))
    if row["url"] in texts:
        return queue, {"item": row, "article_text": texts[row["url"]]}
    try:
        text = reader(row["url"])
        if not isinstance(text, str) or not 350 <= len(text) <= cq.MAX_ARTICLE_CHARS:
            raise ValueError("Dzen article body is unavailable")
    except Exception as error:
        row.update(status="read_error", attempts=row["attempts"] + 1, last_attempt_at=cq.stamp(now))
        if isinstance(error, TextAccessStopped):
            queue["text_blocked"] = {"at": cq.stamp(now), "reason": str(error)}
        return queue, None
    if row["status"] != "generation_error":
        row["status"] = "pending"
    return queue, {"item": row, "article_text": text}


def generate(candidate, media, previous, config, now, api_key, *, model=None):
    if not candidate or not api_key or media["generator"]["status"] not in {"ok", "idle", "read_error"}:
        return
    usage = media["usage"]
    old_usage = previous.get("usage", {}) if previous.get("schema_version") == 1 else {}
    before = int(old_usage.get("attempted", 0)) if old_usage.get("date") == usage["date"] else 0
    if usage["attempted"] >= config["max_per_day"] or usage["attempted"] - before >= config["max_per_run"]:
        return
    row = candidate["item"]
    context = [{"id": row["id"], "title": row["title"], "article_text": candidate["article_text"]}]
    usage["attempted"] += 1
    row.update(attempts=row["attempts"] + 1, last_attempt_at=cq.stamp(now))
    try:
        result = cq.validate_comments((model or cq.ask_model)(context, api_key), context)[row["id"]]
        comment = result["comment"]
        matched = [word.casefold() for word in re.findall(r"\w+", comment)]
        article = " " + " ".join(re.findall(r"\w+", candidate["article_text"].casefold())) + " "
        quoting = any(" " + " ".join(matched[i:i+8]) + " " in article for i in range(len(matched) - 7))
        if result["status"] == "draft_ready" and (result["fact_review"] != "passed" or quoting
                or api_key in comment or re.search(r"\b(?:Bearer\s+\S+|AIza[\w-]{15,})", comment, re.I)):
            result = {"status": "skipped_by_editor", "comment": "", "fact_review": "rejected"}
        row.update({key: result[key] for key in ("status", "comment", "fact_review")}, generated_at=cq.stamp(now))
    except Exception:
        # Dzen response errors can contain private context; they stay out of media diagnostics.
        row.update(status="generation_error", comment="")


def run_optional_dzen(args, config, previous, media, now, api_key):
    submitted = {}
    if args.submitted_text and args.submitted_text.is_file():
        try:
            value = json.loads(args.submitted_text.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                submitted = value
        except (OSError, ValueError):
            print("First Car submitted text unavailable")
    discovery = json.loads(args.discovery.read_text(encoding="utf-8"))
    old_drafts = json.loads(args.drafts_state.read_text(encoding="utf-8"))
    drafts, candidate = prepare(discovery, old_drafts, media, config, now,
                                allowed=os.environ.get("FIRST_CAR_ARTICLE_TEXT") == "enabled",
                                api_key=api_key, submitted=submitted)
    generate(candidate, media, previous, config, now, api_key)
    for row in drafts["items"]:
        for key in row.keys() - PUBLIC_FIELDS:
            del row[key]
        if row.get("status") != "draft_ready" or row.get("fact_review") != "passed":
            row.pop("comment", None)
    args.drafts_output.write_text(json.dumps(drafts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def first_car_timeout(_signum, _frame):
    raise TimeoutError("First Car exceeded its optional time budget")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("state", "output", "discovery", "drafts-state", "drafts-output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--submitted-text", type=Path)
    args = parser.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    config = cq.load_config(cq.ROOT / "data/commenting_sources.json")
    previous = json.loads(args.state.read_text(encoding="utf-8"))
    media = cq.build_queue(config, previous, now, api_key=api_key)
    # The GitHub-hosted runner is Linux. Leave time to save the completed publisher batch.
    prior = signal.signal(signal.SIGALRM, first_car_timeout)
    try:
        signal.alarm(55)
        run_optional_dzen(args, config, previous, media, now, api_key)
    except Exception:
        print("First Car draft preparation unavailable")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prior)
    args.output.write_text(json.dumps(media, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
