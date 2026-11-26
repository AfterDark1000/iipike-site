#!/usr/bin/env python3
"""HPII automatic editor stage 2: ordinary-only GitHub claim inbox and draft validator.

The request consumer runs inside GitHub Actions, not in ChatGPT. It is deliberately
incapable of approving, publishing, writing covers or editing production articles.
"""
import argparse
import copy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.site_news_pool import validate as validate_pool, utc_time, stamp, canonical_url
from scripts.site_rubrics import RUBRICS as SITE_RUBRICS

REQUESTS = Path("data/auto_editor/requests")
RECEIPTS = Path("data/auto_editor/receipts")
POOL = Path("data/site_news_pool.json")
DRAFTS = Path("editorial_inbox/auto_drafts")
REQUEST_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{4,100}\.json\Z")
POOL_ID = re.compile(r"n-[0-9a-f]{16}\Z")
ARTICLE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
STATES = {"drafting", "ready_for_review", "blocked"}
MAX_NEW_CLAIMS_PER_24H = 5  # Hard production safeguard, counted from immutable reserved receipts.
RUBRICS = frozenset(SITE_RUBRICS)  # Same editorial keys as the site's canonical taxonomy.
CYRILLIC = dict(zip(
    "абвгдежзийклмнопрстуфхцчшщъыьэюя",
    ("a", "b", "v", "g", "d", "e", "zh", "z", "i", "y", "k",
     "l", "m", "n", "o", "p", "r", "s", "t", "u", "f", "kh",
     "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya")
))

def valid_request(path):
    if (path.is_symlink() or not path.is_file() or not REQUEST_NAME.fullmatch(path.name)
            or path.stat().st_size > 4096):
        raise ValueError("Invalid immutable auto-editor request filename or size")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (type(data) is dict and set(data) == {"schema_version", "action", "worker", "dispatch_sha"}
            and type(data["schema_version"]) is int and data["schema_version"] == 2
            and data["action"] == "claim_ordinary" and data["worker"] == "hpii-auto-editor"
            and isinstance(data["dispatch_sha"], str)
            and re.fullmatch(r"[0-9a-f]{40}", data["dispatch_sha"])):
        return data
    if (type(data) is not dict or set(data) != {"schema_version", "action", "worker"}
            or type(data["schema_version"]) is not int or data["schema_version"] != 1
            or data["action"] != "claim_ordinary"
            or data["worker"] != "hpii-auto-editor"):
        raise ValueError("Request must contain exactly the supported claim_ordinary action")
    return data

def request_order(root=ROOT):
    root = Path(root)
    directory = root / REQUESTS
    if not directory.exists():
        return []
    paths = list(directory.iterdir())
    if any(p.is_symlink() or not p.is_file() or not REQUEST_NAME.fullmatch(p.name)
           for p in paths):
        raise ValueError("Invalid request inbox entries")
    present = {p.relative_to(root).as_posix(): p for p in paths}
    proc = subprocess.run([
        "git", "-C", str(root), "log", "--reverse", "--diff-filter=A",
        "--format=", "--name-only", "--", REQUESTS.as_posix()
    ], text=True, capture_output=True, check=True)
    ordered = []
    for line in proc.stdout.splitlines():
        key = line.strip()
        if key in present and key not in ordered:
            ordered.append(key)
    if len(ordered) != len(present):
        raise ValueError("Request has no immutable Git creation history")
    return [present[k] for k in ordered]

def article_slug(item):
    """Stable, human-readable transliterated slug bound to the original pool ID."""
    chars = []
    for char in item["title"].casefold().replace("ё", "е"):
        chars.append(CYRILLIC.get(char, char))
    prefix = re.sub(r"[^a-z0-9]+", "-", "".join(chars)).strip("-")
    prefix = prefix[:49].rstrip("-") or "story"
    value = prefix + "-" + item["id"][2:18]
    if len(value) > 72 or not ARTICLE_ID.fullmatch(value):
        raise ValueError("Article slug invalid")
    return value

def claim_ordinary(pool, request_filename, *, now=None, used_ids=(), routing=None, strict_routes=False):
    """Claim only standalone ordinary long stories; skip all linked groups."""
    from scripts.editorial_routing import load_routes, long_allowed, effective_priority
    validate_pool(pool)
    if routing is None:
        routing = load_routes(pool)
    if not REQUEST_NAME.fullmatch(request_filename):
        raise ValueError("Invalid request filename")
    # Linked groups are deliberately reserved for the human editor.
    # Both the leading article and its companion stories are excluded:
    # the autonomous Work editor should handle only standalone news.
    def standalone(item):
        route = routing.get(item["id"], {})
        return ((not strict_routes or (route.get("lane") == "long" and route.get("decision") == "full"))
                and route.get("decision") not in ("linked_primary", "linked_secondary")
                and "group" not in route and "group_primary" not in route)

    pending = [i for i in pool["items"]
               if i["status"] == "queued" and i["priority"] in ("normal", "low")
               and effective_priority(i, routing) != "high"
               and long_allowed(i, routing) and standalone(i)]
    if not pending:
        return copy.deepcopy(pool), None
    item = min(pending, key=lambda x: x["sequence"])
    assert item["priority"] != "high"
    article_id = article_slug(item)
    if article_id in used_ids or any(
            i["article_id"] == article_id for i in pool["items"] if i["article_id"]):
        raise ValueError("Article ID collision, no reserve made: " + article_id)
    now = now or stamp()
    utc_time(now)
    result = copy.deepcopy(pool)
    target = next(x for x in result["items"] if x["id"] == item["id"])
    target["status"] = "in_review"
    target["review_started_at"] = now
    target["note"] = "AUTO_EDITOR claim=" + request_filename + "; article_id=" + article_id
    validate_pool(result)
    ticket = {
        "pool_id": item["id"], "pool_sequence": item["sequence"],
        "article_id": article_id, "priority": item["priority"],
        "title": item["title"], "source_url": item["source_url"],
        "claimed_at": now, "worker": "hpii-auto-editor"
    }
    return result, ticket

def check_dispatch(root, name, request, now):
    """Resolve the immutable dispatcher assignment and check the live intake guards.
    All Git IO stays server-side; no changes are made by this check.
    """
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, text=True, check=True).stdout.strip()
    sha = request["dispatch_sha"]
    ref = git("rev-parse", "origin/editorial-intake")
    current = git("rev-parse", ref + ":editorial_inbox/auto_editor_dispatch/current.json")
    if current != sha:
        # A timer may refresh current.json between request and consumption.
        # Accept only an exact historic dispatcher blob reachable on intake,
        # and still require its expiry, current guards and current FIFO below.
        history = git("log", "-1", "--format=%H", "--find-object="+sha, ref,
                      "--", "editorial_inbox/auto_editor_dispatch/current.json")
        if not history:
            raise ValueError("DISPATCH_STALE: unknown assignment blob")
    ticket = json.loads(git("cat-file", "blob", sha))
    job = ticket.get("job") or {}
    if (ticket.get("schema_version") != 1 or ticket.get("status") != "ready"
            or job.get("kind") != "new" or job.get("request") != name
            or not utc_time(ticket["prepared_at"]) <= now <= utc_time(ticket["valid_until"])):
        raise ValueError("DISPATCH_INVALID: request does not match a current new assignment")
    for folder in ("auto_drafts", "auto_decisions", "auto_copyedits", "auto_copyedit_responses"):
        path = "editorial_inbox/" + folder
        proc = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", ref+":"+path],
                              capture_output=True, text=True)
        actual = proc.stdout.strip() if proc.returncode == 0 else None
        if path not in ticket["intake_guard"] or actual != ticket["intake_guard"][path]:
            raise ValueError("DISPATCH_STALE: editorial inputs changed: "+path)
    return job["candidate"]["id"]


def consume(root=ROOT, *, now=None, paths=None):
    """Read latest checkout; update pool and all receipts in one Git commit later."""
    root = Path(root)
    now = now or stamp()
    now_utc = utc_time(now)
    original = json.loads((root / POOL).read_text(encoding="utf-8"))
    validate_pool(original)
    current = original
    from scripts.editorial_routing import load_routes, ROUTES
    strict = (root / ROUTES).is_file()
    routes = load_routes(original, root=root) if strict else None
    outputs = {}
    receipt_directory = root / RECEIPTS
    ordered = request_order(root) if paths is None else [Path(p) for p in paths]
    used_ids = set()
    recent_claims = []
    existing = receipt_directory.glob("*.json") if receipt_directory.exists() else ()
    for p in existing:
        rec = json.loads(p.read_text(encoding="utf-8"))
        if rec.get("status") == "reserved":
            used_ids.add(rec["article_id"])
            if rec.get("worker") == "hpii-auto-editor":
                claimed = utc_time(rec["claimed_at"])
                # Strict rolling window; cannot borrow unused future quota.
                if now_utc - timedelta(hours=24) < claimed <= now_utc:
                    recent_claims.append(claimed)
    for path in ordered:
        if path.parent != root / REQUESTS or path.is_symlink():
            raise ValueError("Only direct request inbox files can be consumed")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        receipt_path = receipt_directory / path.name
        if receipt_path.exists():
            old = json.loads(receipt_path.read_text(encoding="utf-8"))
            if old.get("request_sha256") != digest:
                raise ValueError("Immutable request was edited after processing")
            if old.get("status") not in ("reserved", "no_ordinary_news", "rejected"):
                raise ValueError("Invalid existing receipt")
            continue
        try:
            request = valid_request(path)
            exact = (check_dispatch(root, path.name, request, now_utc)
                     if request["schema_version"] == 2 else None)
            if exact is not None and not strict:
                raise ValueError("DISPATCH_INVALID: explicit routing required")
            if len(recent_claims) >= MAX_NEW_CLAIMS_PER_24H:
                raise ValueError("AUTO_EDITOR_DAILY_CAP_5: rolling 24-hour reservation quota reached")
            updated, ticket = claim_ordinary(current, path.name, now=now,
                                             used_ids=used_ids, routing=routes, strict_routes=strict)
            if exact is not None and (ticket is None or ticket["pool_id"] != exact):
                raise ValueError("DISPATCH_FIFO_CHANGED: no substitute reserved")
            current = updated
            receipt = {
                "schema_version": 1, "request": path.name,
                "request_sha256": digest,
                "status": "reserved" if ticket else "no_ordinary_news",
                **(ticket or {})
            }
            if ticket:
                used_ids.add(ticket["article_id"])
                recent_claims.append(now_utc)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            # Fail closed: invalid input NEVER changes the pool.
            receipt = {"schema_version": 1, "request": path.name,
                       "request_sha256": digest, "status": "rejected",
                       "error": str(exc)[:400]}
        outputs[path.name] = receipt
    validate_pool(current)
    if current != original:
        (root / POOL).write_text(json.dumps(current, indent=2, ensure_ascii=False)
                                 + "\n", encoding="utf-8")
    receipt_directory.mkdir(parents=True, exist_ok=True)
    for name, receipt in outputs.items():
        (receipt_directory / name).write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return outputs

def draft_template(receipt):
    """Create a recoverable *unapproved* stub after a confirmed claim."""
    if receipt.get("status") != "reserved":
        raise ValueError("Only reserved receipts can start drafts")
    return {
        "schema_version": 1, "request": receipt["request"],
        "pool_id": receipt["pool_id"], "pool_sequence": receipt["pool_sequence"],
        "article_id": receipt["article_id"], "status": "drafting",
        "revision": 1, "created_at": receipt["claimed_at"],
        "updated_at": receipt["claimed_at"],
        "content": {
            "title": "", "dzen_title": "", "summary": "", "rubric": "",
            "section": "", "topics": [], "companies": [], "products": [],
            "source_url": "", "source_title": "", "event_date": None,
            "related_dzen_ids": [], "site_crosslinks": {},
            "article_markdown": "", "threads_text": "", "x_text": "",
            "vk_title": "", "vk_summary": ""
        },
        "research": {"sources": [], "fact_checks": [], "notes": ""},
        "entity_candidates": {"companies": [], "products": []},
        "cover_brief": {"fact": "", "hook": "", "constraints": ""},
        "editor_notes": []
    }

def validate_draft(doc, receipt):
    """No approval fields. Readiness requires the *entire* editorial package."""
    if not isinstance(doc, dict):
        raise ValueError("Draft must be an object")
    expected = set(draft_template(receipt))
    if set(doc) != expected:
        raise ValueError("Unapproved draft fields missing/extra, approval metadata forbidden")
    if (doc["schema_version"] != 1 or doc["request"] != receipt["request"]
            or doc["pool_id"] != receipt["pool_id"]
            or doc["pool_sequence"] != receipt["pool_sequence"]
            or doc["article_id"] != receipt["article_id"]
            or doc["status"] not in STATES
            or type(doc["revision"]) is not int or doc["revision"] < 1):
        raise ValueError("Invalid draft claim binding, revision or status")
    utc_time(doc["created_at"])
    utc_time(doc["updated_at"])
    if utc_time(doc["updated_at"]) < utc_time(doc["created_at"]):
        raise ValueError("Draft updated before created")
    body = doc["content"]
    if not isinstance(body, dict) or set(body) != set(draft_template(receipt)["content"]):
        raise ValueError("Draft content fields missing/extra")
    for key in ("topics", "companies", "products", "related_dzen_ids"):
        if (not isinstance(body[key], list) or
                not all(isinstance(s, str) for s in body[key])):
            raise ValueError("Invalid list field: " + key)
    if not isinstance(body["site_crosslinks"], dict):
        raise ValueError("Invalid site_crosslinks")
    if (not isinstance(doc["research"], dict)
            or set(doc["research"]) != {"sources", "fact_checks", "notes"}
            or not isinstance(doc["research"]["sources"], list)
            or not isinstance(doc["research"]["fact_checks"], list)
            or not isinstance(doc["research"]["notes"], str)
            or not isinstance(doc["entity_candidates"], dict)
            or set(doc["entity_candidates"]) != {"companies", "products"}
            or not all(isinstance(doc["entity_candidates"][k], list)
                       for k in ("companies", "products"))
            or not isinstance(doc["cover_brief"], dict)
            or set(doc["cover_brief"]) != {"fact", "hook", "constraints"}
            or not all(isinstance(doc["cover_brief"][k], str)
                       for k in ("fact", "hook", "constraints"))
            or not isinstance(doc["editor_notes"], list)):
        raise ValueError("Draft research, candidates or cover brief invalid")
    if doc["status"] == "ready_for_review":
        for key in ("title", "dzen_title", "summary", "rubric", "section", "source_url",
                    "source_title", "article_markdown", "threads_text", "x_text",
                    "vk_title", "vk_summary"):
            if not isinstance(body[key], str) or not body[key].strip():
                raise ValueError("Ready draft missing: " + key)
        if body["title"] != body["dzen_title"] or body["rubric"] not in RUBRICS:
            raise ValueError("Ready draft title/rubric invalid")
        canonical_url(body["source_url"])
        if len(body["threads_text"]) > 480 or len(body["x_text"]) > 280:
            raise ValueError("Social text too long")
        if len(body["vk_title"]) > 200 or len(body["vk_summary"]) > 350:
            raise ValueError("VK text too long")
        if len(body["related_dzen_ids"]) > 4 or len(body["topics"]) > 3:
            raise ValueError("Too many crosslinks/topics")
        if len(body["companies"]) > 4 or len(body["products"]) > 4:
            raise ValueError("Too many entities")
        for key in ("fact", "hook", "constraints"):
            if not doc["cover_brief"][key].strip():
                raise ValueError("Incomplete cover brief: " + key)
        if not doc["research"]["sources"] or not doc["research"]["fact_checks"]:
            raise ValueError("Ready draft missing research evidence")
        from scripts.site_rich_text import markdown_to_blocks
        markdown_to_blocks(body["article_markdown"])
    return doc

def verify_drafts(draft_directory, receipt_directory):
    """Check files physically present on editorial-intake against *main* receipts."""
    directory = Path(draft_directory)
    receipts = Path(receipt_directory)
    if not directory.exists():
        return []
    validated = []
    for path in sorted(directory.iterdir()):
        if path.is_symlink() or not path.is_file():
            raise ValueError("Unexpected draft directory entry")
        if path.suffix != ".json":
            if path.name in (".gitkeep", "README.md"):
                continue
            raise ValueError("Unexpected file in drafts directory")
        if not ARTICLE_ID.fullmatch(path.stem) or len(path.stem) > 72:
            raise ValueError("Unsafe draft filename")
        if path.stat().st_size > 262144:
            raise ValueError("Oversized draft")
        doc = json.loads(path.read_text(encoding="utf-8"))
        request = doc.get("request")
        if not isinstance(request, str) or not REQUEST_NAME.fullmatch(request):
            raise ValueError("Invalid draft request pointer")
        receipt_path = receipts / request
        if not receipt_path.is_file():
            raise ValueError("Missing confirmed GitHub claim receipt")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("status") != "reserved":
            raise ValueError("Draft references an unreserved or rejected claim")
        validate_draft(doc, receipt)
        if path.stem != doc["article_id"]:
            raise ValueError("Draft path does not match article ID")
        validated.append(doc["article_id"])
    return validated

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consume", action="store_true")
    parser.add_argument("--verify-drafts", type=Path)
    parser.add_argument("--draft-template", type=Path,
                        help="Print empty draft JSON from a confirmed receipt")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.consume:
        result = consume()
    elif args.verify_drafts:
        result = {"validated": verify_drafts(args.verify_drafts, ROOT / RECEIPTS)}
    elif args.draft_template:
        receipt = json.loads(args.draft_template.read_text(encoding="utf-8"))
        result = draft_template(receipt)
    else:
        parser.error("Specify an operation")
    if args.report:
        args.report.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
