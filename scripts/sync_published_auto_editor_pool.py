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
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import site_news_pool
CLAIM = re.compile(
    r"AUTO_EDITOR claim=([a-z0-9][a-z0-9._-]*[.]json); "
    r"article_id=([a-z0-9]+(?:-[a-z0-9]+)*)\Z"
)

def git_text(root, *args):
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL)


def git_json(root, *args):
    obj = json.loads(git_text(root, *args))
    if not isinstance(obj, dict):
        raise ValueError("Expected editorial object")
    return obj


def approved_source_change(root, item, claim, public):
    """Accept a different primary URL only with the exact human-approved draft.

    Do not modify the discovery URL or infer that two URLs are equivalent.
    Bind original immutable receipt -> draft blob -> human text decision ->
    actual handoff -> current approved story and published catalog.
    """
    request, sid = claim.groups()
    try:
        receipt_path = root / "data/auto_editor/receipts" / request
        if receipt_path.is_symlink() or not receipt_path.is_file():
            return False
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (receipt.get("status") != "reserved"
                or receipt.get("worker") != "hpii-auto-editor"
                or receipt.get("request") != request
                or receipt.get("pool_id") != item["id"]
                or receipt.get("pool_sequence") != item["sequence"]
                or receipt.get("article_id") != sid
                or receipt.get("claimed_at") != item["review_started_at"]
                or site_news_pool.canonical_url(receipt["source_url"]) !=
                    site_news_pool.canonical_url(item["source_url"])):
            return False
        ref = git_text(root, "rev-parse", "refs/remotes/origin/editorial-intake").strip()
        if not re.fullmatch(r"[0-9a-f]{40}", ref):
            return False
        story_path = "editorial_inbox/stories/" + sid + ".json"
        story = git_json(root, "show", ref + ":" + story_path)
        new_source = site_news_pool.canonical_url(public["source_url"])
        if (story.get("id") != sid or story.get("status") != "editor_approved"
                or story.get("approved_by") != "human_editor" or not story.get("approved_at")
                or site_news_pool.canonical_url(story["source_url"]) != new_source):
            return False
        directory = "editorial_inbox/auto_handoffs/"
        names = git_text(root, "ls-tree", "-r", "--name-only", ref, "--", directory).splitlines()
        pattern = re.compile(re.escape(directory + sid) + r"-r[1-9][0-9]*-v[1-9][0-9]*[.]json\Z")
        for name in names:
            if not pattern.fullmatch(name):
                continue
            handoff = git_json(root, "show", ref + ":" + name)
            draft_sha = handoff.get("source_draft_blob_sha")
            decision_sha = handoff.get("text_decision_blob_sha")
            rev = handoff.get("text_revision")
            if (handoff.get("article_id") != sid or handoff.get("status") != "handed_off_to_site_queue"
                    or handoff.get("story_path") != story_path
                    or type(rev) is not int or rev < 1
                    or not all(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha)
                               for sha in (draft_sha, decision_sha))):
                continue
            draft = git_json(root, "cat-file", "blob", draft_sha)
            decision = git_json(root, "cat-file", "blob", decision_sha)
            if (draft.get("request") == request and draft.get("pool_id") == item["id"]
                    and draft.get("pool_sequence") == item["sequence"]
                    and draft.get("article_id") == sid and draft.get("revision") == rev
                    and draft.get("status") == "ready_for_review"
                    and site_news_pool.canonical_url(draft["content"]["source_url"]) == new_source
                    and decision.get("article_id") == sid and decision.get("revision") == rev
                    and decision.get("action") == "approve_text"
                    and decision.get("draft_blob_sha") == draft_sha
                    and decision.get("decided_by") == "AfterDark1000"
                    and decision.get("channel") == "hpii-admin-oauth-gateway"
                    and decision.get("decided_at") == handoff.get("text_approved_at")
                    and decision.get("decided_at")):
                site_news_pool.utc_time(decision["decided_at"])
                return True
        return False
    except (OSError, subprocess.CalledProcessError, ValueError, TypeError,
            KeyError, AttributeError):
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
        # canonicalized ORIGINAL source URL. Never match on headline alone.
        if public.get("url") != "articles/" + sid + "/":
            raise ValueError("Published article has an unexpected path: " + sid)
        if (site_news_pool.canonical_url(public.get("source_url")) !=
                site_news_pool.canonical_url(item["source_url"]) and
                not approved_source_change(root, item, claim, public)):
            raise ValueError("Published article source differs from claim: " + sid)
        when = public.get("published_at_utc")
        if not isinstance(when, str):
            raise ValueError("Published article is missing a real timestamp: " + sid)
        site_news_pool.utc_time(when)
        page = root / "articles" / sid / "index.html"
        if not page.is_file() or page.is_symlink():
            raise ValueError("Published article is absent from actual site files: " + sid)

        note = item["note"].rstrip() + "\n" + "Опубликовано на сайте: https://iipike.ru/" + public["url"]
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
