#!/usr/bin/env python3
"""Reconcile ONLY published autonomous-editor full articles with their raw pool claims.

No approval, draft generation, publishing, Dzen, or social posting.
Run against freshly checked-out main after the site-first release step.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import subprocess

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import site_news_pool
CLAIM = re.compile(
    r"AUTO_EDITOR claim=([a-z0-9][a-z0-9._-]*[.]json); "
    r"article_id=([a-z0-9]+(?:-[a-z0-9]+)*)\Z"
)


def intake_record(root, ref, path):
    """Read exact committed bytes and calculate their Git blob identity."""
    read = subprocess.run(
        ["git", "show", ref + ":" + path], cwd=root,
        capture_output=True, check=False,
    )
    if read.returncode:
        return None, None
    raw = read.stdout
    sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    return json.loads(raw), sha


def verified_source_upgrade(root, item, public, request, *, intake_ref):
    """A different URL is allowed ONLY with a bound, human-approved handoff.

    The immutable reservation preserves the original discovery URL. The
    approved draft may use a better source; never infer identity from title,
    a shared domain, or an article ID alone.
    """
    if not intake_ref:
        return False
    sid = public["id"]
    try:
        receipt = json.loads((root / "data/auto_editor/receipts" / request).read_text(encoding="utf-8"))
        if (receipt.get("request") != request or receipt.get("status") != "reserved"
                or receipt.get("worker") != "hpii-auto-editor"
                or receipt.get("article_id") != sid or receipt.get("pool_id") != item["id"]
                or receipt.get("pool_sequence") != item["sequence"]
                or site_news_pool.canonical_url(receipt.get("source_url"))
                != site_news_pool.canonical_url(item["source_url"])
                or site_news_pool.utc_time(receipt.get("claimed_at"))
                != site_news_pool.utc_time(item["review_started_at"])):
            return False
        request_bytes = (root / "data/auto_editor/requests" / request).read_bytes()
        if hashlib.sha256(request_bytes).hexdigest() != receipt.get("request_sha256"):
            return False
        approved = json.loads((root / "content/approved" / (sid + ".json")).read_text(encoding="utf-8"))
        if (approved.get("slug") != sid or approved.get("status") != "approved"
                or approved.get("published_at_utc") != public.get("published_at_utc")
                or approved.get("title") != public.get("title")
                or site_news_pool.canonical_url(approved.get("source_url"))
                != site_news_pool.canonical_url(public.get("source_url"))):
            return False
        draft, draft_sha = intake_record(root, intake_ref, "editorial_inbox/auto_drafts/" + sid + ".json")
        if (not draft or draft.get("article_id") != sid or draft.get("request") != request
                or draft.get("pool_id") != item["id"] or draft.get("pool_sequence") != item["sequence"]
                or draft.get("status") != "ready_for_review"
                or type(draft.get("revision")) is not int or draft["revision"] < 1
                or site_news_pool.utc_time(draft.get("created_at"))
                != site_news_pool.utc_time(receipt.get("claimed_at"))):
            return False
        fields = ("title", "article_markdown", "source_url")
        if any(not isinstance(approved.get(k), str) or not approved[k]
               or draft.get("content", {}).get(k) != approved[k] for k in fields):
            return False
        revision = draft["revision"]
        stem = sid + "-r" + str(revision)
        decision, decision_sha = intake_record(root, intake_ref, "editorial_inbox/auto_decisions/" + stem + ".json")
        if (not decision or decision.get("article_id") != sid or decision.get("revision") != revision
                or decision.get("updated_at") != draft.get("updated_at")
                or decision.get("draft_blob_sha") != draft_sha
                or decision.get("action") != "approve_text"
                or decision.get("status") != "text_approved_cover_pending"
                or decision.get("channel") != "hpii-admin-oauth-gateway"
                or not decision.get("decided_by")):
            return False
        story_path = "editorial_inbox/stories/" + sid + ".json"
        story, _ = intake_record(root, intake_ref, story_path)
        if (not story or story.get("id") != sid or story.get("status") != "editor_approved"
                or story.get("approved_by") != "human_editor"
                or any(story.get(k) != approved[k] for k in fields)):
            return False
        for version in range(1, 6):
            key = stem + "-v" + str(version) + ".json"
            handoff, _ = intake_record(root, intake_ref, "editorial_inbox/auto_handoffs/" + key)
            if (not handoff or handoff.get("article_id") != sid
                    or handoff.get("text_revision") != revision or handoff.get("cover_version") != version
                    or handoff.get("status") != "handed_off_to_site_queue"
                    or handoff.get("source_draft_blob_sha") != draft_sha
                    or handoff.get("text_decision_blob_sha") != decision_sha
                    or handoff.get("story_path") != story_path):
                continue
            cover, cover_sha = intake_record(root, intake_ref, "editorial_inbox/auto_cover_decisions/" + key)
            if (cover and cover.get("article_id") == sid
                    and cover.get("text_revision") == revision and cover.get("cover_version") == version
                    and cover.get("action") == "approve_cover"
                    and cover.get("status") == "cover_approved_handoff_pending"
                    and cover.get("channel") == "hpii-admin-oauth-gateway" and cover.get("decided_by")
                    and cover.get("source_draft_blob_sha") == draft_sha
                    and cover_sha == handoff.get("cover_decision_blob_sha")
                    and cover.get("cover_blob_sha") == handoff.get("cover_blob_sha")
                    and site_news_pool.utc_time(decision.get("decided_at"))
                    <= site_news_pool.utc_time(public.get("published_at_utc"))
                    and site_news_pool.utc_time(cover.get("decided_at"))
                    <= site_news_pool.utc_time(public.get("published_at_utc"))):
                return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False
    return False


def reconcile(pool, news, *, root, intake_ref=None):
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
        changed_source = (site_news_pool.canonical_url(public.get("source_url"))
                          != site_news_pool.canonical_url(item["source_url"]))
        if changed_source and not verified_source_upgrade(root, item, public, claim.group(1), intake_ref=intake_ref):
            raise ValueError("Published article source differs from claim without verified editorial handoff: " + sid)
        when = public.get("published_at_utc")
        if not isinstance(when, str):
            raise ValueError("Published article is missing a real timestamp: " + sid)
        site_news_pool.utc_time(when)
        page = root / "articles" / sid / "index.html"
        if not page.is_file() or page.is_symlink():
            raise ValueError("Published article is absent from actual site files: " + sid)

        note = item["note"].rstrip() + "\n" + "Опубликовано на сайте: https://iipike.ru/" + public["url"]
        if changed_source:
            note += "\nИсточник уточнён при редакционной проверке: " + public["source_url"]
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
    # Pin a single immutable editorial snapshot for the entire reconciliation.
    ref = subprocess.run(["git", "rev-parse", "--verify", "refs/remotes/origin/editorial-intake^{commit}"],
                         cwd=root, capture_output=True, text=True, check=False)
    return reconcile(pool, news, root=root, intake_ref=ref.stdout.strip() if ref.returncode == 0 else None)


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
