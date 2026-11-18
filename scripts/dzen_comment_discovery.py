#!/usr/bin/env python3
"""Read licensed search/data APIs for direct Dzen publication links.

Pilot only: does NOT request dzen.ru, publish comments, or modify commenting/queue.json.
No results are labelled fresh unless a publication timestamp is supplied by the
Dzen-data provider. Search-engine indexing timestamps are NOT publication dates.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MOSCOW = ZoneInfo("Europe/Moscow")
UTC = dt.timezone.utc
KEYS_BASE = "https://api.keys.so"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
ARTICLE = re.compile(r"^/a/[A-Za-z0-9_-]{8,100}$")
MEDIA = re.compile(r"^/media/id/[0-9a-f]{24}/[0-9a-f]{24}$", re.I)
TOPIC = re.compile(
    r"\b(?:ии|ai|llm|gpt|chatgpt|claude|gemini|grok|deepseek|qwen|sora|"
    r"openai|anthropic|copilot)\b|нейросет|искусственн.{0,12}интеллект|"
    r"дипфейк|робот|машинн.{0,10}обучен|автоматизац|нейромодел", re.I
)


def direct_article_url(raw):
    """Only a canonical, direct Dzen article/post URL. Never a search/channel URL."""
    if not isinstance(raw, str):
        return None
    try:
        p = urllib.parse.urlsplit(raw)
        if (p.scheme != "https" or p.hostname not in {"dzen.ru", "www.dzen.ru"}
                or p.username or p.password or p.port or
                not (ARTICLE.fullmatch(p.path) or MEDIA.fullmatch(p.path))):
            return None
        return "https://dzen.ru" + p.path
    except ValueError:
        return None


def channel_url(raw):
    if not isinstance(raw, str):
        return None
    try:
        p = urllib.parse.urlsplit(raw)
        if (p.scheme != "https" or p.hostname not in {"dzen.ru", "www.dzen.ru"}
                or p.username or p.password or p.port):
            return None
        if re.fullmatch(r"/(?:id/[0-9a-f]{24}|[a-zA-Z0-9._-]{2,80})", p.path, re.I):
            return "https://dzen.ru" + p.path
    except ValueError:
        pass
    return None


def as_date(raw, *, default_tz=MOSCOW):
    if isinstance(raw, dict):
        raw = raw.get("date")
    if not isinstance(raw, str):
        return None
    try:
        value = dt.datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=default_tz)
        return value.astimezone(UTC)
    except ValueError:
        return None


def metric(raw):
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        value = int(raw)
        return value if value >= 0 else None
    except (ValueError, TypeError):
        return None


def make_row(raw, provider):
    if not isinstance(raw, dict):
        return None
    direct = direct_article_url(raw.get("canonicalUrl")) or direct_article_url(raw.get("url"))
    title = str(raw.get("title") or "").strip()
    description = str(raw.get("description") or "")
    if not direct or len(title) < 10 or not TOPIC.search(title + " " + description):
        return None
    pub = as_date(raw.get("datePublishAt")) if provider == "keys_so" else None
    channel = channel_url(raw.get("url")) if provider == "keys_so" else None
    return {
        "id": hashlib.sha256(direct.encode()).hexdigest()[:24],
        "dzen_url": direct,
        "title": title[:300],
        "description": description[:500],
        "channel_name": str(raw.get("channelTitle") or raw.get("channel_name") or "")[:120],
        "channel_url": channel,
        "published_at": pub.isoformat() if pub else None,
        "date_status": "provider_publication_date" if pub else "unknown",
        "indexed_at": str(raw.get("page_age") or "")[:60] if provider == "brave" else None,
        "views": metric(raw.get("countViews")),
        "comments": metric(raw.get("countComments")),
        "subscribers": metric(raw.get("subscribers")),
        "source": provider,
        "link_status": "provider_link_unopened",
    }


def score(row):
    views = row["views"] or 0
    comments = row["comments"] or 0
    subscribers = row["subscribers"]
    small_bonus = 7 if subscribers is not None and subscribers <= 10_000 else 0
    return small_bonus + min(views // 500, 15) + min(comments * 2, 20)


def compile_results(keys_rows, brave_rows, config, *, now=None):
    now = now or dt.datetime.now(UTC)
    age = dt.timedelta(hours=config["max_age_hours"])
    dedup = {}
    stats = defaultdict(int)
    for provider, rows in (("brave", brave_rows), ("keys_so", keys_rows)):
        for raw in rows:
            stats["seen_" + provider] += 1
            row = make_row(raw, provider)
            if not row:
                stats["irrelevant_or_not_direct"] += 1
                continue
            pub = as_date(row["published_at"], default_tz=UTC)
            if pub and not (dt.timedelta(0) <= now - pub <= age):
                stats["outdated_or_future"] += 1
                continue
            prev = dedup.get(row["dzen_url"])
            if prev:
                stats["duplicates"] += 1
                # Data provider date and metrics beat search index metadata.
                if row["date_status"] == "provider_publication_date":
                    row["indexed_at"] = prev.get("indexed_at")
                    dedup[row["dzen_url"]] = row
            else:
                dedup[row["dzen_url"]] = row

    ranked = sorted(dedup.values(),
                    key=lambda r: (r["date_status"] == "provider_publication_date",
                                   score(r), r.get("published_at") or ""), reverse=True)
    ready, needs_date, channels = [], [], {}
    counts = defaultdict(int)
    for row in ranked:
        target = ready if row["date_status"] == "provider_publication_date" else needs_date
        group = row["channel_url"] or row["channel_name"] or row["id"]
        if counts[group] >= config["per_channel_limit"]:
            stats["channel_cap"] += 1
            continue
        if len(target) >= config["max_items"]:
            stats["item_cap"] += 1
            continue
        counts[group] += 1
        target.append(row)
        if row["channel_url"]:
            channels[row["channel_url"]] = {
                "url": row["channel_url"], "name": row["channel_name"],
                "subscribers": row["subscribers"],
            }
    return {
        "schema_version": 1, "mode": "independent_pilot",
        "updated_at": now.isoformat(),
        "rules": {"max_age_hours": config["max_age_hours"],
                  "no_direct_dzen_requests": True,
                  "not_connected_to_commenting_queue": True},
        "ready": ready,
        "needs_publication_date": needs_date,
        "channel_candidates": list(channels.values()),
        "stats": dict(stats),
    }


def get_json(base, params, headers):
    url = base + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.url.split("?", 1)[0] != base:
            raise ValueError("Unexpected provider redirect")
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("Provider result exceeds size limit")
    return json.loads(body.decode("utf-8"))


def fetch_keys(config, token):
    headers = {"X-Keyso-TOKEN": token, "Accept": "application/json"}
    rows = []
    for page in range(1, config["keys_top_pages"] + 1):
        payload = get_json(KEYS_BASE + "/zen/channel/new/top/publications",
                           {"sort": "datePublishAt|desc", "forDay": 3,
                            "page": page, "per_page": 25}, headers)
        if not isinstance(payload.get("data"), list):
            raise ValueError("Invalid Keys.so publications response")
        rows.extend(payload["data"])
    for channel in config["channels"]:
        payload = get_json(KEYS_BASE + "/zen/channel/publications",
                           {"channel": channel, "sort": "datePublishAt|desc",
                            "page": 1, "per_page": 25}, headers)
        if not isinstance(payload.get("data"), list):
            raise ValueError("Invalid Keys.so channel response")
        for item in payload["data"]:
            if isinstance(item, dict):
                item = dict(item)
                item.setdefault("url", channel)
                rows.append(item)
    return rows


def fetch_brave(config, token):
    headers = {"X-Subscription-Token": token, "Accept": "application/json"}
    rows = []
    for query in config["queries"][:config["brave_queries_per_run"]]:
        payload = get_json(BRAVE_URL,
                           {"q": query + " site:dzen.ru", "count": 20,
                            "freshness": "pw", "search_lang": "ru"},
                           headers)
        items = payload.get("web", {}).get("results", [])
        if not isinstance(items, list):
            raise ValueError("Invalid Brave results response")
        rows.extend(items)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--live", action="store_true", help="Use licensed external APIs")
    group.add_argument("--fixture", type=Path, help="Offline JSON: keys/brave arrays")
    parser.add_argument("--config", type=Path,
                        default=ROOT / "data/commenting_dzen_discovery.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    keys_rows, brave_rows, health = [], [], {}
    if args.fixture:
        fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
        keys_rows = fixture.get("keys", [])
        brave_rows = fixture.get("brave", [])
        health = {"fixture": "offline; no external sources checked"}
    else:
        sources = [
            ("keys_so", os.environ.get("KEYS_SO_API_TOKEN"), fetch_keys),
            ("brave", os.environ.get("BRAVE_SEARCH_API_KEY"), fetch_brave),
        ]
        for name, token, fn in sources:
            if not token:
                health[name] = "not_configured"
                continue
            try:
                rows = fn(config, token)
                if name == "keys_so":
                    keys_rows = rows
                else:
                    brave_rows = rows
                health[name] = "ok"
            except Exception as exc:
                health[name] = "error: " + type(exc).__name__
    output = compile_results(keys_rows, brave_rows, config)
    output["providers"] = health
    output["coverage"] = "unverified" if not any(s == "ok" for s in health.values()) else "partial"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"providers": health, "ready": len(output["ready"]),
                      "needs_date": len(output["needs_publication_date"])}, ensure_ascii=False))
    return 0 if any(s == "ok" for s in health.values()) or args.fixture else 2


if __name__ == "__main__":
    sys.exit(main())
