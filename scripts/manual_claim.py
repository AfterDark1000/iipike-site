#!/usr/bin/env python3
"""Fallback for manual ChatGPT editor claims; never publishes or approves.

All writes must be committed together on a fresh main snapshot, with a
non-force push and a full retry after any conflicting update.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import site_news_pool, editorial_routing

POOL = Path("data/site_news_pool.json")
REQUESTS = Path("data/editorial_claims/requests")
RECEIPTS = Path("data/editorial_claims/receipts")
NAME = re.compile(r"manual-[a-z0-9][a-z0-9_-]{7,95}\.json\Z")
BODY = {"schema_version": 1, "action": "claim_next", "worker": "hpii-manual-editor"}


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def consume(root=ROOT, *, now=None):
    root = Path(root)
    original = json.loads((root / POOL).read_text(encoding="utf-8"))
    site_news_pool.validate(original)
    route_path = root / editorial_routing.ROUTES
    if not route_path.is_file():
        raise ValueError("Missing routing registry; refusing manual claim")
    routes_doc = json.loads(route_path.read_text(encoding="utf-8"))
    routes = editorial_routing.validate_document(routes_doc, original, require_all=True)
    current = original
    req_dir, rec_dir = root / REQUESTS, root / RECEIPTS
    out = {}
    if not req_dir.exists():
        return out
    for path in sorted(req_dir.iterdir()):
        if path.is_symlink() or not path.is_file() or not NAME.fullmatch(path.name):
            raise ValueError("Unsafe manual claim request entry")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        receipt = rec_dir / path.name
        base = {"schema_version": 1, "request": path.name,
                "request_sha256": digest, "worker": BODY["worker"]}
        if receipt.exists() or receipt.is_symlink():
            if receipt.is_symlink() or not receipt.is_file():
                raise ValueError("Unsafe manual claim receipt")
            old = json.loads(receipt.read_text(encoding="utf-8"))
            if (any(old.get(k) != v for k, v in base.items()) or
                    old.get("status") not in {"reserved", "no_long_news", "rejected"}):
                raise ValueError("Invalid or modified acknowledged manual claim")
            continue
        try:
            if len(raw) > 4096:
                raise ValueError("Request too large")
            req = json.loads(raw)
            if (type(req) is not dict or type(req.get("schema_version")) is not int
                    or req != BODY):
                raise ValueError("Invalid manual claim request")
        except (ValueError, TypeError, UnicodeError) as exc:
            out[path.name] = {**base, "status": "rejected", "error": str(exc)[:400]}
            continue
        # Canonical Python logic owns FIFO, effective priority, route and status.
        # Do not suppress errors from the actual pool/route validation.
        current, item = site_news_pool.next_item(current, now=now, routing=routes)
        if item is None:
            out[path.name] = {**base, "status": "no_long_news"}
        else:
            out[path.name] = {**base, "status": "reserved",
                "pool_id": item["id"], "pool_sequence": item["sequence"],
                "claimed_at": item["review_started_at"],
                "effective_priority": editorial_routing.effective_priority(item, routes)}
    site_news_pool.validate(current)
    editorial_routing.validate_document(routes_doc, current, require_all=True)
    if current != original:
        dump(root / POOL, current)
    for name, record in out.items():
        dump(rec_dir / name, record)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consume", action="store_true", required=True)
    args = parser.parse_args()
    print(json.dumps(consume(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
