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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import site_news_pool
CLAIM = re.compile(
    r"AUTO_EDITOR claim=([a-z0-9][a-z0-9._-]*[.]json); "
    r"article_id=([a-z0-9]+(?:-[a-z0-9]+)*)\Z"
)


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
        if site_news_pool.canonical_url(public.get("source_url")) != site_news_pool.canonical_url(item["source_url"]):
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
