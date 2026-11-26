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
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import site_news_pool, editorial_routing

POOL = Path("data/site_news_pool.json")
REQUESTS = Path("data/editorial_claims/requests")
RECEIPTS = Path("data/editorial_claims/receipts")
NAME = re.compile(r"manual-[a-z0-9][a-z0-9_-]{7,95}\.json\Z")
BODY = {"schema_version": 1, "action": "claim_next", "worker": "hpii-manual-editor"}

STATES = {"reserved", "no_long_news", "rejected", "probe_ok", "checkpointed", "returned", "closed_rejected", "closed_approved"}
COMMON = {"schema_version", "action", "worker"}
BOUND = COMMON | {"claim_request", "pool_id", "pool_sequence", "claimed_at", "expected_note", "note"}


def approved_story(root, req):
    slug, sha = req["article_id"], req["story_sha"]
    if not isinstance(slug, str) or not site_news_pool.SLUG.fullmatch(slug):
        raise ValueError("Invalid article ID")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Invalid approved story blob SHA")
    path = "refs/remotes/origin/editorial-intake:editorial_inbox/stories/" + slug + ".json"
    try:
        actual = subprocess.check_output(["git", "rev-parse", path], cwd=root, text=True).strip()
        if actual != sha:
            raise ValueError("Approved story changed")
        story = json.loads(subprocess.check_output(["git", "cat-file", "blob", sha], cwd=root))
    except subprocess.CalledProcessError as exc:
        raise ValueError("Approved story not found in editorial-intake") from exc
    if (story.get("id") != slug or story.get("status") != "editor_approved"
            or story.get("approved_by") != "human_editor" or not story.get("approved_at")):
        raise ValueError("Story not explicitly human-approved")


def bound_action(root, current, req, base, now):
    action = req["action"]
    fields = BOUND | ({"article_id", "story_sha", "human_authorized"} if action == "approve"
                      else {"human_authorized"} if action == "return" else set())
    if set(req) != fields or (action in {"return", "approve"} and req.get("human_authorized") is not True):
        raise ValueError("Invalid bound request or missing human authorization")
    name = req["claim_request"]
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError("Invalid original claim request")
    receipt_path = root / RECEIPTS / name
    request_path = root / REQUESTS / name
    if any(p.is_symlink() or not p.is_file() for p in (receipt_path, request_path)):
        raise ValueError("Missing original manual claim")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (receipt.get("status") != "reserved" or receipt.get("worker") != BODY["worker"]
            or receipt.get("request") != name
            or receipt.get("request_sha256") != hashlib.sha256(request_path.read_bytes()).hexdigest()
            or json.loads(request_path.read_bytes()) != BODY
            or any(receipt.get(k) != req[k] for k in ("pool_id", "pool_sequence", "claimed_at"))):
        raise ValueError("Claim identity mismatch")
    item = next((i for i in current["items"] if i["id"] == req["pool_id"]), None)
    if (item is None or item["status"] != "in_review" or item["sequence"] != req["pool_sequence"]
            or item["review_started_at"] != req["claimed_at"] or item["note"] != req["expected_note"]
            or item["note"].startswith(("AUTO_EDITOR claim=", "SHORT_EDITOR claim="))):
        raise ValueError("Stale or foreign reservation/checkpoint")
    note = req["note"]
    if not isinstance(note, str) or not note.strip() or len(note) > 1500:
        raise ValueError("Invalid checkpoint or decision note")
    if note.startswith(("AUTO_EDITOR claim=", "SHORT_EDITOR claim=")):
        raise ValueError("Foreign worker marker forbidden")
    if action == "checkpoint":
        changed, target = site_news_pool.checkpoint(current, item["id"], note)
        status = "checkpointed"
    else:
        if action == "approve":
            approved_story(root, req)
        changed, target = site_news_pool.transition(current, item["id"], action,
            article_id=req.get("article_id"), note=note, now=now)
        status = {"return": "returned", "reject": "closed_rejected", "approve": "closed_approved"}[action]
    return changed, {**base, "status": status, "pool_id": target["id"],
                     "pool_sequence": target["sequence"], "pool_status": target["status"],
                     "claimed_at": target["review_started_at"], "note": target["note"]}


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
                    old.get("status") not in STATES):
                raise ValueError("Invalid or modified acknowledged manual claim")
            continue
        try:
            if len(raw) > 4096:
                raise ValueError("Request too large")
            req = json.loads(raw)
            if (type(req) is not dict or type(req.get("schema_version")) is not int
                    or req.get("worker") != BODY["worker"]
                    or req.get("action") not in {"claim_next", "probe", "checkpoint", "return", "reject", "approve"}):
                raise ValueError("Invalid manual claim request")
            action = req["action"]
            if action in {"claim_next", "probe"} and set(req) != COMMON:
                raise ValueError("Invalid claim/probe fields")
            if action in {"checkpoint", "return", "reject", "approve"}:
                current, out[path.name] = bound_action(root, current, req, base, now)
                continue
        except (ValueError, TypeError, UnicodeError, KeyError) as exc:
            out[path.name] = {**base, "status": "rejected", "error": str(exc)[:400]}
            continue
        # Canonical Python logic owns FIFO, effective priority, route and status.
        # Do not suppress errors from the actual pool/route validation.
        stamp = now or datetime.now(timezone.utc).isoformat(timespec="microseconds")
        proposed, item = site_news_pool.next_item(current, now=stamp, routing=routes)
        if action == "probe":
            site_news_pool.validate(proposed)
            editorial_routing.validate_document(routes_doc, proposed, require_all=True)
            out[path.name] = {**base, "status": "probe_ok", "pool_unchanged": True,
                              "candidate_available": item is not None}
            continue
        current = proposed
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
