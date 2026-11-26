#!/usr/bin/env python3
"""Atomic short-news requests for GitHub Actions; never publish or approve."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
import re

from scripts import site_news_pool, editorial_routing

ROOT = Path(__file__).resolve().parents[1]
POOL = Path("data/site_news_pool.json")
REQUESTS = Path("data/briefs/claims/requests")
RECEIPTS = Path("data/briefs/claims/receipts")
REQUEST_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{4,100}\.json\Z")


def read_request(path):
    if (path.is_symlink() or not path.is_file() or
            not REQUEST_NAME.fullmatch(path.name) or path.stat().st_size > 4096):
        raise ValueError("Invalid short-editor request file")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if (type(obj) is not dict or type(obj.get("schema_version")) is not int or
            obj.get("schema_version") != 1 or obj.get("worker") != "hpii-short-editor"):
        raise ValueError("Invalid short-editor request body")
    if obj.get("action") == "return_to_long":
        if (set(obj) != {"schema_version", "action", "worker", "pool_id",
                         "pool_sequence", "claimed_at"} or
                not re.fullmatch(r"n-[0-9a-f]{16}", str(obj["pool_id"])) or
                type(obj["pool_sequence"]) is not int or obj["pool_sequence"] < 1 or
                not isinstance(obj["claimed_at"], str)):
            raise ValueError("Invalid short-to-long request body")
        site_news_pool.utc_time(obj["claimed_at"])
        return obj
    if (obj.get("action") != "claim_short" or
            not set(obj) <= {"schema_version", "action", "worker", "count"}):
        raise ValueError("Invalid short-editor request body")
    count = obj.get("count", 1)
    if type(count) is not int or not 1 <= count <= 5:
        raise ValueError("Short-editor request count must be 1..5")
    return count


def return_to_long(pool, route_doc, candidates, approved, req):
    """Return only the exact unapproved short reservation; keep FIFO sequence."""
    rid = req["pool_id"]
    item = next((x for x in pool["items"] if x["id"] == rid), None)
    if (item is None or item["sequence"] != req["pool_sequence"] or
            item["status"] != "in_review" or
            item["review_started_at"] != req["claimed_at"] or
            item["note"] != "SHORT_EDITOR claim=short; pool_id=" + rid):
        raise ValueError("Short-editor reservation missing, stale or owned by another worker")
    route = next((x for x in route_doc["items"] if x["pool_id"] == rid), None)
    if (route is None or route["lane"] != "short" or route["decision"] != "short"
            or "group" in route):
        raise ValueError("Item is not an independent short route")
    if any(x["pool_id"] == rid for x in approved["items"]):
        raise ValueError("Approved short news cannot be returned")
    drafts = [x for x in candidates["items"] if x["pool_id"] == rid]
    if len(drafts) > 1 or any(x["status"] != "pending_review" for x in drafts):
        raise ValueError("Conflicting short candidate")
    next_pool, target = site_news_pool.transition(
        pool, rid, "return", note="Returned to ordinary full article queue by editor")
    next(i for i in next_pool["items"] if i["id"] == rid)["priority"] = "normal"
    next_routes = copy.deepcopy(route_doc)
    next(r for r in next_routes["items"] if r["pool_id"] == rid).update(
        lane="long", decision="full")
    next_candidates = copy.deepcopy(candidates)
    next_candidates["items"] = [x for x in next_candidates["items"] if x["pool_id"] != rid]
    editorial_routing.validate_document(next_routes, next_pool, require_all=True)
    return next_pool, next_routes, next_candidates, {
        "pool_id": rid, "pool_sequence": target["sequence"], "lane": "long",
        "decision": "full", "priority": "normal", "pool_status": "queued",
        "removed_candidate": drafts[0]["slug"] if drafts else None
    }


def consume(root=ROOT, *, now=None):
    root = Path(root)
    pool_path = root / POOL
    original = json.loads(pool_path.read_text(encoding="utf-8"))
    site_news_pool.validate(original)
    routes = editorial_routing.load_routes(original, root=root, require_all=True)
    current = original
    route_path = root / editorial_routing.ROUTES
    candidate_path = root / editorial_routing.CANDIDATES
    approved_path = root / editorial_routing.APPROVED
    route_doc = json.loads(route_path.read_text(encoding="utf-8")) if route_path.is_file() else None
    candidates = json.loads(candidate_path.read_text(encoding="utf-8")) if candidate_path.is_file() else {"items": []}
    approved = json.loads(approved_path.read_text(encoding="utf-8")) if approved_path.is_file() else {"items": []}
    original_routes, original_candidates = route_doc, candidates
    outputs = {}
    req_dir, rec_dir = root / REQUESTS, root / RECEIPTS
    if not req_dir.exists():
        return outputs
    for path in sorted(req_dir.iterdir()):
        if path.is_symlink() or not path.is_file() or not REQUEST_NAME.fullmatch(path.name):
            raise ValueError("Unsafe short-editor request entry")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        receipt_path = rec_dir / path.name
        if receipt_path.exists():
            old = json.loads(receipt_path.read_text(encoding="utf-8"))
            if old.get("request_sha256") != digest:
                raise ValueError("Immutable short-editor request changed after acknowledgment")
            if old.get("status") not in {"reserved", "no_short_news", "short_work_in_progress", "rejected", "returned_to_long"}:
                raise ValueError("Invalid existing short-editor receipt")
            continue
        try:
            count = read_request(path)
            if isinstance(count, dict):
                if route_doc is None:
                    raise ValueError("Missing routing registry")
                if candidate_path.is_file():
                    from scripts.build_briefs import read_candidates
                    read_candidates(root)
                if approved_path.is_file():
                    from scripts.build_briefs import validated
                    validated(root)
                current, route_doc, candidates, details = return_to_long(
                    current, route_doc, candidates, approved, count)
                routes = editorial_routing.validate_document(route_doc, current, require_all=True)
                outputs[path.name] = {
                    "schema_version": 1, "request": path.name,
                    "request_sha256": digest, "status": "returned_to_long", **details
                }
                continue
            busy = editorial_routing.short_work_in_progress(current, root=root)
            current, items = editorial_routing.claim_short_batch(
                current, count=count, routes=routes, now=now, root=root
            )
            rows = [{
                "pool_id": item["id"], "pool_sequence": item["sequence"],
                "title": item["title"], "source_url": item["source_url"],
                "claimed_at": item["review_started_at"], "worker": "hpii-short-editor"
            } for item in items]
            receipt = {
                "schema_version": 1, "request": path.name,
                "request_sha256": digest,
                "status": "reserved" if items else (
                    "short_work_in_progress" if busy else "no_short_news"
                ),
                "count": len(rows),
                "items": rows,
                # Backward-compatible one-item receipt fields for older short chats.
                **(rows[0] if count == 1 and rows else {})
            }
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            receipt = {
                "schema_version": 1, "request": path.name,
                "request_sha256": digest, "status": "rejected",
                "error": str(exc)[:400]
            }
        outputs[path.name] = receipt
    site_news_pool.validate(current)
    if current != original:
        pool_path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    if route_doc != original_routes:
        route_path.write_text(json.dumps(route_doc, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    if candidates != original_candidates:
        candidate_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
    rec_dir.mkdir(parents=True, exist_ok=True)
    for name, receipt in outputs.items():
        (rec_dir / name).write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consume", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.consume:
        parser.error("Only --consume is supported")
    outcome = consume()
    report = json.dumps(outcome, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
