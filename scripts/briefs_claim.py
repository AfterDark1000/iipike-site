#!/usr/bin/env python3
"""Atomic short-news requests for GitHub Actions; never publish or approve."""
import argparse
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
    if (type(obj) is not dict or not
            {"schema_version", "action", "worker"} <= set(obj) or
            not set(obj) <= {"schema_version", "action", "worker", "count"} or
            obj["schema_version"] != 1 or obj["action"] != "claim_short" or
            obj["worker"] != "hpii-short-editor"):
        raise ValueError("Invalid short-editor request body")
    count = obj.get("count", 1)
    if type(count) is not int or not 1 <= count <= 5:
        raise ValueError("Short-editor request count must be 1..5")
    return count


def consume(root=ROOT, *, now=None):
    root = Path(root)
    pool_path = root / POOL
    original = json.loads(pool_path.read_text(encoding="utf-8"))
    site_news_pool.validate(original)
    routes = editorial_routing.load_routes(original, root=root, require_all=True)
    current = original
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
            if old.get("status") not in {"reserved", "no_short_news", "short_work_in_progress", "rejected"}:
                raise ValueError("Invalid existing short-editor receipt")
            continue
        try:
            count = read_request(path)
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
