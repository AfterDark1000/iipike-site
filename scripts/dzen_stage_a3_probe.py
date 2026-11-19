"""Fetch one public article per control channel for issue #215."""

import hashlib
import json
import sys
from datetime import UTC, datetime
from urllib.error import URLError

from dzen_stage_a_probe import (
    ARTICLE,
    ORIGIN,
    REVIEWED_TERMS,
    TERMS_PATH,
    checked_get,
    http_get,
    observed_response,
    robots_rules,
    timestamp,
)

CHANNELS = (
    ("techinsider", "592fddba7ddde8b70fb1c45f"),
    ("hiaimedia", "667c1be45a0fa42c47a53f59"),
)


def count(value):
    return value if type(value) is int and value >= 0 else None


def publication_date(value, relative):
    try:
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            return datetime.fromtimestamp(int(value), UTC).isoformat(), "exact", "publication_date"
    except (ValueError, OSError, OverflowError):
        pass
    if isinstance(relative, str) and relative.strip():
        return relative.strip(), "relative", "creation_time"
    return None, "unknown", None


def select_article(data, publisher_id):
    channel = data["channel"]
    source = channel["source"]
    items = data["items"]
    if channel["status"] != "ok" or source["publisher_id"] != publisher_id or not isinstance(items, list):
        raise ValueError("Unexpected channel export")

    candidates = []
    for item in items:
        if item.get("publisher_id") != publisher_id or item.get("item_type") != "native":
            continue
        link = item.get("link", "").split("#", 1)[0].split("?", 1)[0]
        title = item.get("title", "").strip()
        views = count(item.get("views"))
        date, date_type, date_field = publication_date(item.get("publication_date"), item.get("creation_time"))
        if not ARTICLE.fullmatch(link) or not title or not views or date is None:
            continue
        social = item.get("socialInfo") or {}
        comments = count(social.get("commentCount"))
        candidates.append({
            "channel": source["title"],
            "channel_subscribers": count(source.get("subscribers")),
            "title": title,
            "url": link,
            "date": date,
            "date_type": date_type,
            "date_field": date_field,
            "creation_time": item.get("creation_time"),
            "views": views,
            "comments": comments,
            "comments_reason": "missing_or_invalid_socialInfo.commentCount" if comments is None else None,
        })
    if not candidates:
        raise ValueError("No article with a date and positive views in the first response")
    # Prefer visible discussion, then views, within the single returned page.
    return max(candidates, key=lambda article: (article["comments"] or 0, article["views"])), len(items)


def run():
    report = {"started_at_utc": timestamp(), "status": "incomplete", "http": [], "publications": []}
    observations = report["http"]
    try:
        status, headers, body = http_get(ORIGIN + "/robots.txt")
        observations.append(observed_response(ORIGIN + "/robots.txt", status, headers))
        if status != 200 or headers.get_content_type() != "text/plain":
            raise ValueError("robots.txt unavailable or unexpected")
        report["robots_sha256"] = hashlib.sha256(body).hexdigest()
        groups = robots_rules(body.decode("utf-8-sig"))

        status, _, body = checked_get(groups, TERMS_PATH, observations)
        report["terms_sha256"] = hashlib.sha256(body).hexdigest()
        if status != 200 or report["terms_sha256"] != REVIEWED_TERMS:
            raise ValueError("Dzen terms unavailable or different from the reviewed revision")

        for slug, publisher_id in CHANNELS:
            path = f"/api/v3/launcher/export?channel_name={slug}"
            status, headers, body = checked_get(groups, path, observations)
            if status != 200 or headers.get_content_type() != "application/json":
                raise ValueError(f"Stopped at {slug} after an unexpected response (HTTP {status})")
            try:
                article, items = select_article(json.loads(body), publisher_id)
            except (AttributeError, KeyError, TypeError) as error:
                raise ValueError(f"Unexpected export schema for {slug}") from error
            observations[-1]["items_in_response"] = items
            report["publications"].append({
                "source": ORIGIN + path,
                "observed_at_utc": observations[-1]["at_utc"],
                "status": "observed",
                **article,
            })
    except (URLError, TimeoutError, ValueError) as error:
        report["reason"] = str(error)
    else:
        report["status"] = "success"
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(result["status"] != "success")
