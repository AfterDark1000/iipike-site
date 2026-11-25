#!/usr/bin/env python3
"""Apply explicitly approved editorial routing decisions via GitHub Actions.

Immutable small request -> SHA-bound receipt; complete pool validator before
any write. Never approve articles, publish, or overwrite active reservations.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import site_news_pool, editorial_routing, editorial_collections

POOL = Path("data/site_news_pool.json")
ROUTES = editorial_routing.ROUTES
REQUESTS = Path("data/editorial_triage/requests")
RECEIPTS = Path("data/editorial_triage/receipts")
NAME = re.compile(r"[a-z0-9][a-z0-9._-]{4,100}\.json\Z")
POOL_ID = re.compile(r"n-[0-9a-f]{16}\Z")
DECISION_LANE = {
    "hot": "long", "full": "long", "linked_primary": "long",
    "short": "short", "linked_secondary": "hold", "defer": "hold",
    "reject_after_verification": "hold", "manual": "hold",
}


def read_request(path):
    if (path.is_symlink() or not path.is_file() or
            not NAME.fullmatch(path.name) or path.stat().st_size > 180000):
        raise ValueError("Invalid immutable triage request name/size")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(doc, dict) and doc.get("action") in {
            "collection_upsert", "collection_release_member"}:
        return editorial_collections.validate_request(doc)
    if (type(doc) is not dict or
            set(doc) != {"schema_version", "action", "worker", "approval", "items"} or
            doc["schema_version"] != 1 or
            doc["action"] != "apply_approved_triage" or
            doc["worker"] != "hpii-morning-triage" or
            doc["approval"] != "explicit_chief_editor_chat_command" or
            not isinstance(doc["items"], list) or not 1 <= len(doc["items"]) <= 500):
        raise ValueError("Invalid approved triage request; explicit approval required")
    seen_ids, seen_seq = set(), set()
    for row in doc["items"]:
        if (type(row) is not dict or
                not {"sequence", "pool_id", "lane", "decision"} <= set(row) or
                not set(row) <= {"sequence", "pool_id", "lane", "decision", "priority",
                                 "group", "group_primary"}):
            raise ValueError("Invalid triage item fields")
        seq, rid, dec, lane = (
            row["sequence"], row["pool_id"], row["decision"], row["lane"])
        if (type(seq) is not int or seq < 1 or
                not isinstance(rid, str) or not POOL_ID.fullmatch(rid) or
                dec not in DECISION_LANE or lane != DECISION_LANE[dec]):
            raise ValueError("Invalid triage ID, sequence or lane")
        if rid in seen_ids or seq in seen_seq:
            raise ValueError("Duplicate triage item in one request")
        seen_ids.add(rid)
        seen_seq.add(seq)
        if ("group" in row) != ("group_primary" in row):
            raise ValueError("Incomplete linked group metadata")
        if "group" in row and (not isinstance(row["group"], str) or
                               not row["group"] or
                               type(row["group_primary"]) is not int or
                               row["group_primary"] < 1):
            raise ValueError("Invalid linked group metadata")
        if "priority" in row and (
                row["priority"] not in {"high", "normal", "low"} or
                (dec == "hot" and row["priority"] != "high") or
                (dec != "hot" and row["priority"] == "high")):
            raise ValueError("Invalid priority for triage decision")
    return doc


def apply_request(pool, routes_doc, request, *, source):
    """Pure no-side-effect merge with fail-closed conflicts and intact WIP."""
    site_news_pool.validate(pool)
    editorial_routing.validate_document(routes_doc, pool)
    updated = copy.deepcopy(pool)
    result = copy.deepcopy(routes_doc)
    by_id = {x["id"]: x for x in updated["items"]}
    original_routing = {x["pool_id"]: x for x in result["items"]}
    applied, unchanged, skipped = [], [], []
    for row in request["items"]:
        item = by_id.get(row["pool_id"])
        seq = row["sequence"]
        if item is None or item["sequence"] != seq:
            skipped.append({"sequence": seq, "reason": "missing_or_changed_id"})
            continue
        if item["status"] != "queued":
            skipped.append({"sequence": seq, "reason": "already_reserved_or_closed"})
            continue
        clean_row = {k: v for k, v in row.items() if k != "priority"}
        current = original_routing.get(item["id"])
        new_priority = ("high" if row["decision"] == "hot" else
                        row.get("priority", item["priority"]))
        if current == clean_row and item["priority"] == new_priority:
            unchanged.append(seq)
            continue
        original_routing[item["id"]] = clean_row
        item["priority"] = new_priority
        applied.append(seq)
    result["items"] = sorted(original_routing.values(), key=lambda x: x["sequence"])
    if applied:
        result["source"] = source
        result["approved_date"] = site_news_pool.stamp()[:10]
        result["note"] = "Approved decisions merged by immutable GitHub triage request; no publishing."
    site_news_pool.validate(updated)
    editorial_routing.validate_document(result, updated)
    return updated, result, {
        "applied": applied, "unchanged": unchanged, "skipped": skipped
    }


def consume(root=ROOT):
    root = Path(root)
    pool_path, route_path = root / POOL, root / ROUTES
    pool = json.loads(pool_path.read_text(encoding="utf-8"))
    route = json.loads(route_path.read_text(encoding="utf-8"))
    site_news_pool.validate(pool)
    editorial_routing.validate_document(route, pool, require_all=True)
    collections_path = root / editorial_collections.PATH
    collections = (json.loads(collections_path.read_text(encoding="utf-8"))
                   if collections_path.exists() else editorial_collections.empty())
    editorial_collections.validate_document(collections, pool, route)
    orig_pool, orig_route, orig_collections = (
        copy.deepcopy(pool), copy.deepcopy(route), copy.deepcopy(collections))
    req_dir, rec_dir = root / REQUESTS, root / RECEIPTS
    outputs = {}
    if not req_dir.exists():
        return outputs
    for req_path in sorted(req_dir.iterdir()):
        if req_path.is_symlink() or not req_path.is_file() or not NAME.fullmatch(req_path.name):
            raise ValueError("Unsafe triage request entry")
        digest = hashlib.sha256(req_path.read_bytes()).hexdigest()
        receipt_path = rec_dir / req_path.name
        if receipt_path.exists():
            old = json.loads(receipt_path.read_text(encoding="utf-8"))
            if old.get("request_sha256") != digest:
                raise ValueError("Approved triage request was changed after applying")
            if old.get("status") not in {"applied", "partial_conflict", "no_changes", "rejected"}:
                raise ValueError("Invalid triage receipt")
            continue
        try:
            request = read_request(req_path)
            source = (REQUESTS / req_path.name).as_posix()
            if request["action"] in {"collection_upsert", "collection_release_member"}:
                next_pool, next_route, next_collections, summary = (
                    editorial_collections.apply_request(
                        pool, route, collections, request, source=source))
            else:
                next_pool, next_route, summary = apply_request(
                    pool, route, request, source=source)
                next_collections = collections
            # Rejected requests cannot leave partial mutations for later requests.
            editorial_collections.validate_document(
                next_collections, next_pool, next_route)
            pool, route, collections = next_pool, next_route, next_collections
            outcome = ("partial_conflict" if summary["skipped"] else
                       "applied" if summary["applied"] else "no_changes")
            receipt = {
                "schema_version": 1, "request": req_path.name,
                "request_sha256": digest, "status": outcome, **summary
            }
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            receipt = {
                "schema_version": 1, "request": req_path.name,
                "request_sha256": digest, "status": "rejected",
                "error": str(exc)[:450]
            }
        outputs[req_path.name] = receipt
    site_news_pool.validate(pool)
    editorial_routing.validate_document(route, pool, require_all=True)
    editorial_collections.validate_document(collections, pool, route)
    if collections != orig_collections:
        collections_path.parent.mkdir(parents=True, exist_ok=True)
        collections_path.write_text(
            json.dumps(collections, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    if pool != orig_pool:
        pool_path.write_text(json.dumps(pool, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    if route != orig_route:
        route_path.write_text(json.dumps(route, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    rec_dir.mkdir(parents=True, exist_ok=True)
    for name, doc in outputs.items():
        (rec_dir / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consume", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        pool = json.loads((ROOT / POOL).read_text(encoding="utf-8"))
        doc = json.loads((ROOT / ROUTES).read_text(encoding="utf-8"))
        collections_path = ROOT / editorial_collections.PATH
        collections = (json.loads(collections_path.read_text(encoding="utf-8"))
                       if collections_path.exists() else editorial_collections.empty())
        editorial_collections.validate_document(collections, pool, doc)
        print({"routes": len(editorial_routing.validate_document(doc, pool, require_all=True)),
               "collections": len(collections["items"])})
        return
    if not args.consume:
        parser.error("Use --consume or --check")
    print(json.dumps(consume(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
