#!/usr/bin/env python3
"""Free, autonomous Dzen direct-link discovery from external RSS/Atom feeds.

No dzen.ru requests. No login, anti-bot circumvention, article scraping, or comments.
Only public search-news feeds and optionally user-configured Google Alerts RSS.
An RSS appearance date is never reported as Dzen's publication date.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT = Path(__file__).resolve().parents[1]
UTC = dt.timezone.utc
ALLOWED_FEED_HOSTS = {"news.google.com", "www.bing.com", "www.google.com"}
TOPIC = re.compile(
    r"\b(?:ии|ai|llm|gpt|chatgpt|claude|gemini|grok|deepseek|qwen|sora|openai|"
    r"anthropic|copilot|midjourney)\b|нейросет|искусственн.{0,14}интеллект|"
    r"дипфейк|робот|автоматизац|машинн.{0,10}обучен|нейромодел", re.I
)
ARTICLE = re.compile(r"^/(?:a|b)/[A-Za-z0-9_-]{8,100}$")
LEGACY = re.compile(r"^/media/[A-Za-z0-9._-]{2,100}/[A-Za-z0-9._-]{6,180}$")
URLISH = re.compile(r'https?://[^\s\'"<>]+', re.I)


def safe_direct_link(raw: str | None) -> str | None:
    if not isinstance(raw, str):
        return None
    raw = html.unescape(raw).strip()
    try:
        parsed = urllib.parse.urlsplit(raw)
        if (parsed.scheme != "https" or parsed.hostname not in {"dzen.ru", "www.dzen.ru"}
                or parsed.port is not None or parsed.username or parsed.password):
            return None
        path = urllib.parse.unquote(parsed.path)
        if not (ARTICLE.fullmatch(path) or LEGACY.fullmatch(path)):
            return None
        return "https://dzen.ru" + path
    except ValueError:
        return None


def checked_feed(raw: str) -> str:
    p = urllib.parse.urlsplit(raw)
    if p.scheme != "https" or p.hostname not in ALLOWED_FEED_HOSTS or p.username or p.password or p.port:
        raise ValueError("RSS source host is not allowed")
    if p.hostname == "news.google.com" and p.path != "/rss/search":
        raise ValueError("Invalid Google News RSS path")
    if p.hostname == "www.bing.com" and p.path not in {"/news/search", "/search"}:
        raise ValueError("Invalid Bing News RSS path")
    if p.hostname == "www.google.com" and not re.fullmatch(r"/alerts/feeds/\d+/\d+", p.path):
        raise ValueError("Invalid Google Alerts RSS path")
    return raw


class StrictNoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("RSS redirect not followed")


def read_feed(url: str) -> str:
    checked_feed(url)
    request = urllib.request.Request(url, headers={"User-Agent": "HPII-commenting-link-reader/1.0", "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml"})
    opener = urllib.request.build_opener(StrictNoRedirect)
    with opener.open(request, timeout=18) as response:
        if response.geturl() != url:
            raise ValueError("RSS response URL changed")
        payload = response.read(1_500_001)
        if len(payload) > 1_500_000:
            raise ValueError("RSS feed too large")
    return payload.decode("utf-8-sig", errors="replace")


def tag(element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def get_field(node, names):
    for child in node:
        if tag(child) in names and child.text:
            return child.text.strip()
    return ""


class LinksFromHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
    def handle_starttag(self, name, attrs):
        if name == "a":
            d = dict(attrs)
            if d.get("href"):
                self.hrefs.append(d["href"])


def direct_from_field(value):
    if not isinstance(value, str):
        return []
    value = html.unescape(value)
    direct = safe_direct_link(value)
    if direct:
        return [direct]
    p = urllib.parse.urlsplit(value)
    if p.hostname in {"www.google.com", "google.com"} and p.path == "/url":
        for param in ("url", "q"):
            wrapped = urllib.parse.parse_qs(p.query).get(param, [])
            result = safe_direct_link(wrapped[0]) if wrapped else None
            if result:
                return [result]
    parser = LinksFromHTML()
    try:
        parser.feed(value)
    except (ValueError, TypeError):
        pass
    candidates = parser.hrefs + URLISH.findall(value)
    out = []
    for candidate in candidates:
        candidate = candidate.rstrip(",.);]»")
        link = safe_direct_link(candidate)
        if link and link not in out:
            out.append(link)
    return out


def parse_date(text):
    if not text:
        return None
    try:
        value = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            value = parsedate_to_datetime(text)
        except (ValueError, TypeError, IndexError):
            return None
    if value.tzinfo is None:
        return None
    return value.astimezone(UTC)


def parse_feed(xml: str, source: str):
    root = ET.fromstring(xml)
    if tag(root) not in {"rss", "feed", "rdf"}:
        raise ValueError("Unexpected RSS/Atom root")
    if len(xml) > 1_500_000:
        raise ValueError("Feed too large")
    rows = []
    for node in root.iter():
        if tag(node) not in {"item", "entry"}:
            continue
        title = re.sub(r"<[^>]+>", "", html.unescape(get_field(node, {"title"}))).strip()
        desc = get_field(node, {"description", "summary", "content", "encoded"})
        link_values = []
        for child in node:
            if tag(child) == "link":
                if child.text:
                    link_values.append(child.text.strip())
                if child.attrib.get("href"):
                    link_values.append(child.attrib["href"])
            if tag(child) == "id" and child.text:
                link_values.append(child.text)
        if not TOPIC.search(title + " " + re.sub(r"<[^>]+>", " ", desc)):
            continue
        links = []
        for value in link_values + [desc]:
            for direct in direct_from_field(value):
                if direct not in links:
                    links.append(direct)
        reported = parse_date(get_field(node, {"pubdate", "published", "updated", "date"}))
        for direct in links:
            rows.append({"dzen_url": direct, "title": title[:260], "source": source,
                         "feed_date": reported.isoformat() if reported else None})
    return rows


def feed_urls(config, secrets=""):
    feeds = []
    for q in config.get("queries", []):
        query = q + " site:dzen.ru"
        if config.get("google_news", True):
            feeds.append(("Google News RSS", "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query, "hl": "ru", "gl": "RU", "ceid": "RU:ru"})))
        if config.get("bing_news", True):
            feeds.append(("Bing News RSS", "https://www.bing.com/news/search?" + urllib.parse.urlencode({"q": query, "format": "rss"})))
        if config.get("bing_web", True):
            feeds.append(("Bing Web RSS", "https://www.bing.com/search?" + urllib.parse.urlencode({"q": q + " site:dzen.ru/a/", "format": "rss"})))
    for i, raw in enumerate(secrets.splitlines()):
        raw = raw.strip()
        if raw:
            feeds.append((f"Google Alerts RSS {i+1}", checked_feed(raw)))
    return feeds


def build_queue(collected, previous, now, config):
    max_age = dt.timedelta(days=config.get("history_days", 14))
    old = {x["dzen_url"]: x for x in previous.get("items", [])
           if x.get("dzen_url") and parse_date(x.get("first_seen_at"))
           and now - parse_date(x["first_seen_at"]) <= max_age}
    added = 0
    for row in collected:
        direct = safe_direct_link(row.get("dzen_url"))
        if not direct:
            continue
        if direct not in old:
            added += 1
            old[direct] = {
                "id": hashlib.sha256(direct.encode()).hexdigest()[:24],
                "dzen_url": direct,
                "title": row.get("title") or "Статья Дзена",
                "source": row.get("source") or "RSS",
                "first_seen_at": now.isoformat(),
                "feed_date": row.get("feed_date"),
                "feed_date_status": "provided" if row.get("feed_date") else "unknown",
                "dzen_publication_date": None,
                "date_note": "Дата публикации в Дзене не подтверждена",
                "views": None, "comments": None, "subscribers": None,
                "url_status": "discovered_unopened",
            }
        elif row.get("title") and old[direct].get("title") == "Статья Дзена":
            old[direct]["title"] = row["title"]
    ordered = sorted(old.values(), key=lambda x: x["first_seen_at"], reverse=True)
    return {"schema_version": 1, "updated_at": now.isoformat(),
            "mode": "free_automatic_discovery", "new_items": added,
            "items": ordered[:config.get("max_items", 300)]}


def run(config, previous=None, fetcher=read_feed, secrets="", now=None):
    now = now or dt.datetime.now(UTC)
    previous = previous or {}
    health, collected = [], []
    for label, url in feed_urls(config, secrets):
        try:
            results = parse_feed(fetcher(url), label)
            recent = []
            for row in results:
                observed = parse_date(row.get("feed_date"))
                if observed:
                    if not (dt.timedelta(0) <= now - observed <= dt.timedelta(hours=config.get("max_feed_age_hours", 72))):
                        continue
                elif label != "Bing Web RSS":
                    continue
                # Bing web search usually has no publication timestamp; these
                # entries are shown as undated, never treated as recent Dzen posts.
                recent.append(row)
            collected.extend(recent)
            health.append({"source": label, "status": "ok", "direct_matches": len(recent),
                           "total_direct_matches": len(results), "outdated_or_undated": len(results) - len(recent)})
        except Exception as exc:
            health.append({"source": label, "status": "error", "error_type": type(exc).__name__})
    queue = build_queue(collected, previous, now, config)
    queue["sources"] = health
    queue["coverage"] = "partial_unverified" if any(s["status"] == "ok" for s in health) else "none_checked"
    return queue


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=ROOT / "data/commenting_free_hunter.json")
    p.add_argument("--state", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(argv)
    config = json.loads(a.config.read_text(encoding="utf-8"))
    previous = json.loads(a.state.read_text(encoding="utf-8")) if a.state and a.state.exists() else {}
    queue = run(config, previous, secrets=os.environ.get("GOOGLE_ALERTS_FEEDS", ""))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checked": len(queue["sources"]), "ok": sum(s["status"] == "ok" for s in queue["sources"]),
                      "found_total": len(queue["items"]), "new": queue["new_items"]}, ensure_ascii=False))
    return 0 if queue["coverage"] != "none_checked" else 2


if __name__ == "__main__":
    sys.exit(main())
