#!/usr/bin/env python3
"""Reconcile ONLY published autonomous-editor full articles with their raw pool claims.

No approval, draft generation, publishing, Dzen, or social posting.
Run against freshly checked-out main after the site-first release step.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import sys
import subprocess
import hashlib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import site_news_pool
CLAIM = re.compile(
    r"AUTO_EDITOR claim=([a-z0-9][a-z0-9._-]*[.]json); "
    r"article_id=([a-z0-9]+(?:-[a-z0-9]+)*)\Z"
)



def git_read(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)


def verified_source_upgrade(root, item, public, request, sid):
    """Accept a changed primary source ONLY with the original receipt and
    a matching human-approved, handed-off draft that produced the site article.
    A missing/ambiguous/invalid proof must never close the raw claim.
    """
    try:
        receipt = json.loads((root / "data/auto_editor/receipts" / request).read_text(encoding="utf-8"))
        raw_request = (root / "data/auto_editor/requests" / request).read_bytes()
        req = json.loads(raw_request)
        expected = {
            "schema_version": 1, "request": request, "status": "reserved",
            "pool_id": item["id"], "pool_sequence": item["sequence"],
            "article_id": sid, "worker": "hpii-auto-editor",
            "claimed_at": item["review_started_at"],
            "request_sha256": hashlib.sha256(raw_request).hexdigest(),
        }
        if any(receipt.get(k) != v for k, v in expected.items()):
            return False
        if req.get("action") != "claim_ordinary" or req.get("worker") != "hpii-auto-editor":
            return False
        canon = site_news_pool.canonical_url
        if canon(receipt["source_url"]) != canon(item["source_url"]):
            return False
        approved = json.loads((root / "content/approved" / (sid + ".json")).read_text(encoding="utf-8"))
        if (approved.get("slug") != sid or approved.get("status") != "approved" or
                canon(approved["source_url"]) != canon(public["source_url"]) or
                approved.get("published_at_utc") != public.get("published_at_utc")):
            return False
        ref = git_read(root, "rev-parse", "--verify", "refs/remotes/origin/editorial-intake").decode().strip()
        if not re.fullmatch(r"[a-f0-9]{40}", ref):
            return False
        folder = "editorial_inbox/auto_handoffs"
        files = git_read(root, "ls-tree", "--name-only", ref + ":" + folder).decode().splitlines()
        matches = [x for x in files if re.fullmatch(re.escape(sid) + r"-r[1-9]\d*-v[1-9]\d*\.json", x)]
        if len(matches) != 1:
            return False
        marker = json.loads(git_read(root, "show", ref + ":" + folder + "/" + matches[0]))
        revision, version = marker.get("text_revision"), marker.get("cover_version")
        if (type(revision) is not int or type(version) is not int or
                matches[0] != f"{sid}-r{revision}-v{version}.json" or
                marker.get("schema_version") != 1 or marker.get("article_id") != sid or
                marker.get("status") != "handed_off_to_site_queue" or
                marker.get("story_path") != f"editorial_inbox/stories/{sid}.json"):
            return False
        draft_sha, decision_sha = marker.get("source_draft_blob_sha"), marker.get("text_decision_blob_sha")
        if not all(isinstance(x, str) and re.fullmatch(r"[a-f0-9]{40}", x)
                   for x in (draft_sha, decision_sha)):
            return False
        # Read the immutable approved version, not a possibly newer draft.
        draft = json.loads(git_read(root, "cat-file", "blob", draft_sha))
        decision_path = f"editorial_inbox/auto_decisions/{sid}-r{revision}.json"
        if git_read(root, "rev-parse", ref + ":" + decision_path).decode().strip() != decision_sha:
            return False
        decision = json.loads(git_read(root, "cat-file", "blob", decision_sha))
        if any(draft.get(k) != v for k, v in {
            "request": request, "pool_id": item["id"], "pool_sequence": item["sequence"],
            "article_id": sid, "revision": revision, "status": "ready_for_review",
        }.items()):
            return False
        if any(decision.get(k) != v for k, v in {
            "article_id": sid, "revision": revision, "draft_blob_sha": draft_sha,
            "action": "approve_text", "status": "text_approved_cover_pending",
            "decided_by": "AfterDark1000", "updated_at": draft.get("updated_at"),
            "decided_at": marker.get("text_approved_at"),
        }.items()):
            return False
        content = draft["content"]
        story = json.loads(git_read(root, "show", ref + ":" + marker["story_path"]))
        if story.get("id") != sid or story.get("status") != "editor_approved" or story.get("approved_by") != "human_editor":
            return False
        if not isinstance(content.get("article_markdown"), str) or not content["article_markdown"].strip():
            return False
        if not (canon(content["source_url"]) == canon(story["source_url"]) == canon(public["source_url"])):
            return False
        return all(content.get(k) == story.get(k) == approved.get(k) for k in ("title", "article_markdown"))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def reconcile(pool, news, *, root):
    """Close proven publications only. Reject duplicate or conflicting identities."""
    site_news_pool.validate(pool)
    if not isinstance(news, list):
        raise ValueError("Published catalog must be a list")
    root = Path(root)
    by_id = {}
    for article in news:
        if not isinstance(article, dict):
            raise ValueError("Invalid news catalog entry")
        sid = article.get("id")
        if isinstance(sid, str):
            if sid in by_id:
                raise ValueError("Duplicate published article ID: " + sid)
            by_id[sid] = article

    result = copy.deepcopy(pool)
    changes = []
    claimed_ids = set()
    for item in result["items"]:
        if not item["note"].startswith("AUTO_EDITOR claim="):
            continue
        first_line = item["note"].splitlines()[0]
        claim = CLAIM.fullmatch(first_line)
        if claim is None:
            # Unknown or malformed ownership is not a license to close a record.
            continue
        sid = claim.group(2)
        if sid in claimed_ids:
            raise ValueError("Multiple pool claims for autonomous article: " + sid)
        claimed_ids.add(sid)
        if item["status"] != "in_review":
            continue

        public = by_id.get(sid)
        if public is None:
            continue
        # Two independent identity proofs: exact stable article ID and
        # canonicalized original source URL, or verified receipt-to-approved-draft lineage.
        # Never match on headline alone.
        if public.get("url") != "articles/" + sid + "/":
            raise ValueError("Published article has an unexpected path: " + sid)
        source_changed = site_news_pool.canonical_url(public.get("source_url")) != site_news_pool.canonical_url(item["source_url"])
        if source_changed and not verified_source_upgrade(root, item, public, claim.group(1), sid):
            raise ValueError("Published article source differs from claim without verified lineage: " + sid)
        when = public.get("published_at_utc")
        if not isinstance(when, str):
            raise ValueError("Published article is missing a real timestamp: " + sid)
        site_news_pool.utc_time(when)
        page = root / "articles" / sid / "index.html"
        if not page.is_file() or page.is_symlink():
            raise ValueError("Published article is absent from actual site files: " + sid)

        note = item["note"].rstrip() + "\n" + "Опубликовано на сайте: https://iipike.ru/" + public["url"]
        if source_changed:
            note += "\nПервоначальный источник сохранён; утверждённый первоисточник: " + public["source_url"]
        if len(note) > 1500:
            raise ValueError("Pool note would exceed 1500 characters: " + sid)
        item["status"] = "approved"
        item["article_id"] = sid
        item["closed_at"] = when
        item["note"] = note
        changes.append({"sequence": item["sequence"], "pool_id": item["id"], "article_id": sid})

    site_news_pool.validate(result)
    return result, changes


def synchronized(root):
    root = Path(root)
    pool = json.loads((root / "data/site_news_pool.json").read_text(encoding="utf-8"))
    news = json.loads((root / "news.json").read_text(encoding="utf-8"))
    return reconcile(pool, news, root=root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="Update only data/site_news_pool.json, never publication artifacts")
    args = parser.parse_args()
    updated, changed = synchronized(ROOT)
    if args.write and changed:
        (ROOT / "data/site_news_pool.json").write_text(
            json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8"
        )
    print(json.dumps({"reconciled": changed, "count": len(changed),
                      "written": bool(args.write and changed)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
