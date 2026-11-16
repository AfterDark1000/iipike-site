#!/usr/bin/env python3
"""Safe GitHub-side inbox bridge for candidate batches from ChatGPT chats.

Writers create one small immutable JSON request file; only GitHub Actions
reads the entire live pool and calls the canonical add()/validate() routines.
No publishing, no network requests and no edits to editorial or site content.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from scripts.site_news_pool import add, validate, canonical_url

ROOT = Path(__file__).resolve().parents[1]
REQUESTS = Path("data/site_news_intake/requests")
RECEIPTS = Path("data/site_news_intake/receipts")
POOL = Path("data/site_news_pool.json")
NAME = re.compile(r"[a-z0-9][a-z0-9._-]{4,100}\.json\Z")
RECORD_FIELDS = frozenset({"title", "source_url", "summary", "origin", "priority"})


def request_order(root=ROOT):
    """New request files in the order their creation commits reached Git."""
    root = Path(root)
    directory = root / REQUESTS
    if not directory.exists():
        return []
    paths = list(directory.iterdir())
    if any(p.is_dir() or p.is_symlink() or not NAME.fullmatch(p.name) for p in paths):
        raise ValueError("Request directory contains unsafe or unsupported paths")
    present = {p.relative_to(root).as_posix(): p for p in paths}
    result = subprocess.run(
        ["git", "-C", str(root), "log", "--reverse", "--diff-filter=A",
         "--format=", "--name-only", "--", REQUESTS.as_posix()],
        capture_output=True, text=True, check=True,
    )
    order = []
    for line in result.stdout.splitlines():
        name = line.strip()
        if name in present and name not in order:
            order.append(name)
    if len(order) != len(present):
        raise ValueError("Incoming request is not tracked by creation history")
    return [present[name] for name in order]


def parse_request(path):
    """Accept only unapproved news metadata; callers cannot set IDs or statuses."""
    if path.is_symlink() or not NAME.fullmatch(path.name) or path.stat().st_size > 65536:
        raise ValueError("Invalid request name or oversized request (64 KiB max)")
    raw = path.read_bytes()
    request = json.loads(raw)
    if (not isinstance(request, dict)
            or set(request) != {"schema_version", "records"}
            or type(request["schema_version"]) is not int
            or request["schema_version"] != 1
            or not isinstance(request["records"], list)
            or not 1 <= len(request["records"]) <= 40):
        raise ValueError("Request must contain schema_version=1 and 1–40 records")
    for item in request["records"]:
        if (not isinstance(item, dict)
                or not {"title", "source_url"} <= set(item)
                or not set(item) <= RECORD_FIELDS):
            raise ValueError("Unexpected/missing candidate record fields")
        if (not isinstance(item["title"], str)
                or not 5 <= len(item["title"].strip()) <= 320
                or not isinstance(item["source_url"], str)
                or not isinstance(item.get("summary", ""), str)
                or len(item.get("summary", "")) > 1500
                or not isinstance(item.get("origin", ""), str)
                or len(item.get("origin", "")) > 160
                or item.get("priority", "normal") not in ("high", "normal", "low")):
            raise ValueError("Invalid candidate title, URL, origin or priority")
        canonical_url(item["source_url"])
    return request["records"]


def apply_pending(root=ROOT, paths=None):
    """Process all Git-tracked requests once; write receipts for rejected inputs too.

    The receiver remains idempotent after crashes and concurrent pushes.
    Every request's result is bound to the SHA256 of its exact bytes.
    """
    root = Path(root)
    original = json.loads((root / POOL).read_text(encoding="utf-8"))
    validate(original)
    current = original
    order = request_order(root) if paths is None else [Path(p) for p in paths]
    receipts = {}
    summary = {
        "processed_requests": 0, "accepted_requests": 0, "rejected_requests": 0,
        "added_count": 0, "duplicates_count": 0,
    }
    for path in order:
        if path.parent != root / REQUESTS or not NAME.fullmatch(path.name):
            raise ValueError("Only direct files in the request inbox are allowed")
        if path.is_symlink() or not path.is_file():
            raise ValueError("Unsafe incoming request path")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        receipt_path = root / RECEIPTS / path.name
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("request_sha256") != digest:
                raise ValueError("Already processed request was changed: " + path.name)
            if receipt.get("status") not in ("imported", "rejected"):
                raise ValueError("Invalid existing receipt: " + path.name)
            continue

        # Each batch is atomic: invalid candidate => no change to the pool.
        try:
            records = parse_request(path)
            updated, result = add(current, records)
            before = len(current["items"])
            new_items = updated["items"][before:]
            receipt = {
                "schema_version": 1, "request": path.name,
                "request_sha256": digest, "status": "imported",
                "added": [{"sequence": x["sequence"], "id": x["id"], "title": x["title"]}
                          for x in new_items],
                "duplicates": result["duplicates"], "error": None,
            }
            current = updated
            summary["accepted_requests"] += 1
            summary["added_count"] += len(new_items)
            summary["duplicates_count"] += len(result["duplicates"])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            receipt = {
                "schema_version": 1, "request": path.name,
                "request_sha256": digest, "status": "rejected",
                "added": [], "duplicates": [], "error": str(exc)[:300],
            }
            summary["rejected_requests"] += 1
        receipts[receipt_path] = receipt
        summary["processed_requests"] += 1
    validate(current)
    if current != original:
        (root / POOL).write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    (root / RECEIPTS).mkdir(parents=True, exist_ok=True)
    for path, receipt in receipts.items():
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    summary["pool_total"] = len(current["items"])
    summary["queued_total"] = sum(x["status"] == "queued" for x in current["items"])
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Outside-repository JSON report for CI")
    args = parser.parse_args()
    result = apply_pending()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("HPII_INTAKE_RESULT " + json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
