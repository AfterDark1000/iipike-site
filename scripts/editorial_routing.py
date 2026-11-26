#!/usr/bin/env python3
"""Non-publishing editorial route decisions and safe short-news selection.

The original site_news_pool.json schema and four statuses are unchanged.
A route selects the editorial worker; it is never publication approval.
"""
import argparse
import copy
import json
from pathlib import Path
import sys

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from scripts import site_news_pool

ROOT = Path(__file__).resolve().parents[1]
ROUTES = Path("data/editorial_routing.json")
CANDIDATES = Path("data/briefs/candidates.json")
APPROVED = Path("data/briefs/approved.json")
LANES = {"long", "short", "hold"}
DECISIONS = {
    "hot", "full", "short", "linked_primary", "linked_secondary",
    "defer", "reject_after_verification", "manual"
}


def validate_document(doc, pool, *, require_all=True):
    """Validate IDs, immutable sequence and routing coverage against the pool."""
    site_news_pool.validate(pool)
    if (not isinstance(doc, dict) or set(doc) != {
            "schema_version", "approved_date", "source", "source_pool_sha",
            "note", "items"} or doc["schema_version"] != 1 or
            not isinstance(doc["source"], str) or
            not isinstance(doc["note"], str) or
            not isinstance(doc["items"], list)):
        raise ValueError("Invalid routing index header")
    by_id = {i["id"]: i for i in pool["items"]}
    seen_ids, seen_seqs, routes = set(), set(), {}
    for row in doc["items"]:
        if (not isinstance(row, dict) or
                not {"sequence", "pool_id", "lane", "decision"} <= set(row) or
                not set(row) <= {"sequence", "pool_id", "lane", "decision", "group", "group_primary"} or
                type(row["sequence"]) is not int or
                row["lane"] not in LANES or row["decision"] not in DECISIONS):
            raise ValueError("Invalid editorial route entry")
        rid, seq = row["pool_id"], row["sequence"]
        if rid in seen_ids or seq in seen_seqs:
            raise ValueError("Duplicate editorial route")
        seen_ids.add(rid)
        seen_seqs.add(seq)
        expected_lane = ("short" if row["decision"] == "short" else
                         "hold" if row["decision"] in {
                             "linked_secondary", "defer", "reject_after_verification", "manual"}
                         else "long")
        if row["lane"] != expected_lane:
            raise ValueError("Editorial route lane contradicts decision")
        if ("group" in row) != ("group_primary" in row):
            raise ValueError("Incomplete linked group metadata")
        if "group" in row and (
                not isinstance(row["group"], str) or
                type(row["group_primary"]) is not int):
            raise ValueError("Invalid linked group")
        item = by_id.get(rid)
        if item is None:
            if require_all:
                raise ValueError(f"Route missing pool item #{seq}")
            continue
        if item["sequence"] != seq:
            raise ValueError(f"Editorial route ID/sequence mismatch #{seq}")
        routes[rid] = row
    return routes


def load_routes(pool=None, *, root=ROOT, require_all=False):
    path = Path(root) / ROUTES
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    if pool is None:
        pool = json.loads((Path(root) / "data/site_news_pool.json").read_text(encoding="utf-8"))
    return validate_document(doc, pool, require_all=require_all)


def long_allowed(item, routes):
    return routes.get(item["id"], {}).get("lane", "long") == "long"


def effective_priority(item, routes):
    """Promote approved hot stories even before the large raw pool is rewritten."""
    if routes.get(item["id"], {}).get("decision") == "hot":
        return "high"
    return item["priority"]


def short_allowed(item, routes):
    return routes.get(item["id"], {}).get("lane") == "short"


def reserved_brief_ids(root=ROOT):
    """Do not offer a brief that already has a candidate or an approved record."""
    ids = set()
    for path in (CANDIDATES, APPROVED):
        full = Path(root) / path
        if not full.exists():
            continue
        doc = json.loads(full.read_text(encoding="utf-8"))
        if not isinstance(doc.get("items"), list):
            raise ValueError("Malformed brief candidate/approved file")
        ids.update(x["pool_id"] for x in doc["items"])
    return ids


def short_work_in_progress(pool, *, root=ROOT):
    """Block only unfinished chat drafts, NOT approved briefs awaiting site slots.

    Pool status remains in_review until its separate site release. A fully
    editor-approved, candidate-matching brief is completed for the chat stage.
    Publication remains protected by independent owner-Issue/SHA gate.
    """
    from scripts.build_briefs import validated as validated_approvals
    approved_ids = {r["pool_id"] for r in validated_approvals(root)} if (
        (Path(root) / APPROVED).is_file()) else set()
    return any(i["status"] == "in_review" and
               i["note"].startswith("SHORT_EDITOR claim=short; pool_id=")
               and i["id"] not in approved_ids for i in pool["items"])


def next_short(pool, *, routes=None, root=ROOT, exclude_ids=()):
    site_news_pool.validate(pool)
    if short_work_in_progress(pool, root=root):
        return None
    if routes is None:
        routes = load_routes(pool, root=root)
    excluded = set(exclude_ids)
    excluded.update(reserved_brief_ids(root))
    choices = [
        i for i in pool["items"] if i["status"] == "queued"
        and short_allowed(i, routes) and i["id"] not in excluded
    ]
    return copy.deepcopy(min(choices, key=lambda i: i["sequence"])) if choices else None


def claim_short(pool, *, routes=None, now=None, root=ROOT, exclude_ids=()):
    """Pure transaction plan; caller must commit pool via fresh GitHub SHA CAS."""
    item = next_short(pool, routes=routes, root=root, exclude_ids=exclude_ids)
    if item is None:
        return copy.deepcopy(pool), None
    result = copy.deepcopy(pool)
    target = next(i for i in result["items"] if i["id"] == item["id"])
    target["status"] = "in_review"
    target["review_started_at"] = now or site_news_pool.stamp()
    site_news_pool.utc_time(target["review_started_at"])
    target["note"] = "SHORT_EDITOR claim=short; pool_id=" + item["id"]
    site_news_pool.validate(result)
    return result, copy.deepcopy(target)


def claim_short_batch(pool, count=5, *, routes=None, now=None, root=ROOT, exclude_ids=()):
    """Reserve 1..5 short items in one verified pool transaction, not one per command.

    Existing short-editor WIP blocks an additional batch. Every reserved item has
    its own immutable pool ID and status; no text approval or publication happens.
    """
    site_news_pool.validate(pool)
    if type(count) is not int or not 1 <= count <= 5:
        raise ValueError("Short-editor batch size must be 1..5")
    if short_work_in_progress(pool, root=root):
        return copy.deepcopy(pool), []
    if routes is None:
        routes = load_routes(pool, root=root)
    excluded = set(exclude_ids) | reserved_brief_ids(root)
    selected = sorted((
        i for i in pool["items"]
        if i["status"] == "queued" and short_allowed(i, routes)
        and i["id"] not in excluded
    ), key=lambda i: i["sequence"])[:count]
    result = copy.deepcopy(pool)
    timestamp = now or site_news_pool.stamp()
    site_news_pool.utc_time(timestamp)
    ids = {i["id"] for i in selected}
    for item in result["items"]:
        if item["id"] in ids:
            item["status"] = "in_review"
            item["review_started_at"] = timestamp
            item["note"] = "SHORT_EDITOR claim=short; pool_id=" + item["id"]
    site_news_pool.validate(result)
    return result, [copy.deepcopy(i) for i in result["items"] if i["id"] in ids]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--next-short", action="store_true")
    args = parser.parse_args()
    if not args.validate and not args.next_short:
        parser.error("Select --validate or --next-short")
    pool = json.loads((ROOT / "data/site_news_pool.json").read_text(encoding="utf-8"))
    routes = load_routes(pool, require_all=True)
    if args.validate:
        print(json.dumps({
            "routes": len(routes),
            "long": sum(r["lane"] == "long" for r in routes.values()),
            "short": sum(r["lane"] == "short" for r in routes.values()),
            "hold": sum(r["lane"] == "hold" for r in routes.values())
        }, ensure_ascii=False))
    else:
        item = next_short(pool, routes=routes)
        print(json.dumps(item, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
