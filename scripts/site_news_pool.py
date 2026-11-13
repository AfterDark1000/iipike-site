#!/usr/bin/env python3
"""Offline helper for HPII's unapproved, site-only news-candidate pool.

No network, GitHub pushes, website builds, publication or Dzen operations.
Cross-chat agents use the same schema and commit via GitHub's SHA-guarded API.
"""
import argparse
import copy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
POOL_PATH = ROOT / "data" / "site_news_pool.json"
STATES = {"queued", "in_review", "approved", "rejected"}
PRIORITIES = {"high", "normal", "low"}  # high forms the hot editorial lane; other items keep FIFO
EDITORIAL_TZ = ZoneInfo("Asia/Yekaterinburg")
KEYS = {"id", "sequence", "title", "source_url", "summary", "origin", "priority", "status",
        "added_at", "review_started_at", "closed_at", "article_id", "note"}
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
TRACKING = {"fbclid", "gclid", "yclid", "mc_cid", "mc_eid", "igshid"}


def stamp():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_url(value):
    if not isinstance(value, str) or len(value) > 2000 or any(c.isspace() for c in value):
        raise ValueError("Source URL must be a single HTTPS URL")
    url = urlsplit(value)
    if (url.scheme != "https" or not url.hostname or url.username or
            url.password or url.port not in (None, 443)):
        raise ValueError("Source URL must be safe HTTPS")
    pairs = [(k, v) for k, v in parse_qsl(url.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING]
    host = url.hostname.lower() + (":" + str(url.port) if url.port == 443 else "")
    return urlunsplit(("https", host, url.path.rstrip("/") or "/", urlencode(pairs), ""))


def candidate_id(url, title=None):
    """Stable URL ID for legacy entries; title-aware ID when URL is reused."""
    identity = canonical_url(url)
    if title is not None:
        identity += "\n" + clean_title(title)
    return "n-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def clean_title(value):
    return re.sub(r"[^\w]+", " ", value.casefold().replace("ё", "е")).strip()


def utc_time(value):
    if not isinstance(value, str):
        raise ValueError("Expected ISO timestamp")
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Expected ISO timestamp") from exc
    if ts.tzinfo is None:
        raise ValueError("Timestamp must include UTC offset")
    return ts.astimezone(timezone.utc)


def validate(pool):
    if (not isinstance(pool, dict) or set(pool) != {"schema_version", "note", "items"}
            or pool["schema_version"] != 1 or
            not isinstance(pool["note"], str) or not pool["note"] or
            not isinstance(pool["items"], list) or len(pool["items"]) > 5000):
        raise ValueError("Invalid site news pool header")
    ids, titles = set(), set()
    previous_sequence = 0
    for item in pool["items"]:
        if not isinstance(item, dict) or set(item) != KEYS:
            raise ValueError("Candidate has missing or unknown fields")
        if (type(item["sequence"]) is not int or item["sequence"] <= previous_sequence):
            raise ValueError("Items must stay in strictly increasing FIFO sequence order")
        previous_sequence = item["sequence"]
        if (not isinstance(item["title"], str) or not 5 <= len(item["title"]) <= 320 or
                not isinstance(item["summary"], str) or len(item["summary"]) > 1500 or
                not isinstance(item["origin"], str) or len(item["origin"]) > 160 or
                not isinstance(item["note"], str) or len(item["note"]) > 1500):
            raise ValueError("Invalid candidate text fields")
        url = canonical_url(item["source_url"])
        # Existing cross-chat IDs are opaque stable references. Some legacy
        # entries were created by other writers with a different hash recipe;
        # never renumber them or break their approval/review linkage.
        if not isinstance(item["id"], str) or not re.fullmatch(r"n-[0-9a-f]{16}", item["id"]):
            raise ValueError("Candidate ID must be a stable n-hex16 reference")
        if item["priority"] not in PRIORITIES or item["status"] not in STATES:
            raise ValueError("Invalid candidate priority or status")
        utc_time(item["added_at"])
        if item["review_started_at"] is not None:
            utc_time(item["review_started_at"])
        if item["closed_at"] is not None:
            utc_time(item["closed_at"])
        if (item["status"] == "queued" and
                (item["review_started_at"] is not None or item["closed_at"] is not None or item["article_id"] is not None)):
            raise ValueError("Queued item must not have review/closure metadata")
        if (item["status"] == "in_review" and
                (item["review_started_at"] is None or item["closed_at"] is not None or item["article_id"] is not None)):
            raise ValueError("In-review item must have review start and no closure")
        if (item["status"] in {"approved", "rejected"} and item["closed_at"] is None):
            raise ValueError("Closed item requires closed_at")
        if item["status"] == "approved":
            if not isinstance(item["article_id"], str) or not SLUG.fullmatch(item["article_id"]):
                raise ValueError("Approved item requires actual article ID")
        elif item["article_id"] is not None:
            raise ValueError("Only approved items may have an article ID")
        t = clean_title(item["title"])
        if item["id"] in ids or t in titles:
            raise ValueError("Duplicate candidate ID or identical title")
        ids.add(item["id"])
        titles.add(t)
    return pool


def add(pool, records, *, now=None):
    """Append source-backed candidates without changing an existing item's status."""
    validate(pool)
    result = copy.deepcopy(pool)
    if not isinstance(records, list):
        raise ValueError("Expected a list of candidates")
    now = now or stamp()
    utc_time(now)
    known_urls = {canonical_url(i["source_url"]) for i in result["items"]}
    known_titles = {clean_title(i["title"]) for i in result["items"]}
    added, duplicate = [], []
    sequence = max((i["sequence"] for i in result["items"]), default=0)
    for record in records:
        if not isinstance(record, dict) or not {"title", "source_url"} <= set(record):
            raise ValueError("Candidate requires title and source_url")
        title = str(record["title"]).strip()
        url = canonical_url(record["source_url"])
        normalized = clean_title(title)
        if normalized in known_titles:
            duplicate.append(title)
            continue
        sequence += 1
        # A second distinct story from the same release must be allowed.
        # Keep legacy URL-only IDs for first occurrences to preserve every
        # existing record and cross-chat reference.
        identity = candidate_id(url, title) if url in known_urls else candidate_id(url)
        item = {
            "id": identity, "sequence": sequence,
            "title": title, "source_url": url,
            "summary": str(record.get("summary") or "").strip(),
            "origin": str(record.get("origin") or "ручная подборка").strip(),
            "priority": record.get("priority") or "normal",
            "status": "queued", "added_at": now, "review_started_at": None,
            "closed_at": None, "article_id": None, "note": ""
        }
        result["items"].append(item)
        known_urls.add(url)
        known_titles.add(normalized)
        added.append(item["id"])
    validate(result)
    return result, {"added": added, "duplicates": duplicate}


def next_item(pool, *, now=None):
    validate(pool)
    result = copy.deepcopy(pool)
    pending = [x for x in result["items"] if x["status"] == "queued"]
    if not pending:
        return result, None
    # Hot editorial items are selected first, FIFO by immutable sequence.
    # Once hot items are exhausted, ordinary items retain their FIFO order.
    # Normal/low are informational within the ordinary lane.
    item = min(pending, key=lambda x: (0 if x["priority"] == "high" else 1,
                                       x["sequence"]))
    item["status"] = "in_review"
    item["review_started_at"] = now or stamp()
    validate(result)
    return result, copy.deepcopy(item)


def continue_item(pool, *, item_id=None):
    """Read-only resume of the oldest unfinished candidate (or an exact ID).

    This does not start a fresh review and does not reset its review date.
    """
    validate(pool)
    active = [x for x in pool["items"] if x["status"] == "in_review"]
    if item_id is not None:
        active = [x for x in active if x["id"] == item_id]
    return copy.deepcopy(active[0]) if active else None


def local_date(value):
    """Human-facing date in the editorial timezone; UTC data stays unchanged."""
    return utc_time(value).astimezone(EDITORIAL_TZ).strftime("%d.%m.%Y %H:%M") + " (UTC+05:00)"


def checkpoint(pool, item_id, note):
    """Keep a brief durable handoff summary without changing reservation time."""
    validate(pool)
    if not isinstance(note, str) or not note.strip() or len(note) > 1500:
        raise ValueError("Checkpoint note must contain 1-1500 characters")
    result = copy.deepcopy(pool)
    item = next((x for x in result["items"] if x["id"] == item_id), None)
    if item is None or item["status"] != "in_review":
        raise ValueError("Only an in-review item can receive a checkpoint")
    item["note"] = note.strip()
    validate(result)
    return result, copy.deepcopy(item)


def transition(pool, item_id, action, *, article_id=None, note="", now=None):
    validate(pool)
    result = copy.deepcopy(pool)
    item = next((x for x in result["items"] if x["id"] == item_id), None)
    if item is None or item["status"] != "in_review":
        raise ValueError("Item must exist and be in_review")
    if action == "return":
        item.update(status="queued", review_started_at=None, closed_at=None,
                    article_id=None, note=note[:1500])
    elif action in {"approve", "reject"}:
        if action == "approve" and (not article_id or not SLUG.fullmatch(article_id)):
            raise ValueError("Actual article ID required for approval")
        item.update(status="approved" if action == "approve" else "rejected",
                    closed_at=now or stamp(),
                    article_id=article_id if action == "approve" else None,
                    note=note[:1500])
    else:
        raise ValueError("Unsupported transition")
    validate(result)
    return result, copy.deepcopy(item)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=POOL_PATH)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate", action="store_true")
    group.add_argument("--list", action="store_true")
    group.add_argument("--add", type=Path, metavar="CANDIDATES_JSON")
    group.add_argument("--next", action="store_true")
    group.add_argument("--continue-item", nargs="?", const="", metavar="ID")
    group.add_argument("--checkpoint", metavar="ID")
    group.add_argument("--return-item", metavar="ID")
    group.add_argument("--approve", metavar="ID")
    group.add_argument("--reject", metavar="ID")
    parser.add_argument("--article-id")
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    pool = json.loads(args.file.read_text(encoding="utf-8"))
    validate(pool)
    modified, result = None, None
    if args.add:
        modified, result = add(pool, json.loads(args.add.read_text(encoding="utf-8")))
    elif args.next:
        modified, result = next_item(pool)
    elif args.continue_item is not None:
        result = continue_item(pool, item_id=args.continue_item or None)
    elif args.checkpoint:
        modified, result = checkpoint(pool, args.checkpoint, args.note)
    elif args.return_item:
        modified, result = transition(pool, args.return_item, "return", note=args.note)
    elif args.approve:
        modified, result = transition(pool, args.approve, "approve",
                                      article_id=args.article_id, note=args.note)
    elif args.reject:
        modified, result = transition(pool, args.reject, "reject", note=args.note)
    elif args.list:
        result = [{"sequence": i["sequence"], "id": i["id"], "title": i["title"],
                   "status": i["status"], "priority": i["priority"],
                   "added_at_local": local_date(i["added_at"]),
                   "review_started_at_local": (local_date(i["review_started_at"])
                                                if i["review_started_at"] else None)}
                  for i in pool["items"]]
    else:
        result = "Valid pool"
    if modified is not None and modified != pool:
        args.file.write_text(json.dumps(modified, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
