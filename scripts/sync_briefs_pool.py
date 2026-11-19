#!/usr/bin/env python3
"""Mark original raw candidates handled after owner-approved short news is rendered.

Only called after the independent GitHub Issue approval gate and successful
short-news render. Never alters the full article publishing queue.
"""
import argparse
import json
from pathlib import Path
from scripts import build_briefs, site_news_pool

ROOT = Path(__file__).resolve().parents[1]

def synchronized(root):
    rows = build_briefs.released_rows(root)
    path = root / "data/site_news_pool.json"
    pool = json.loads(path.read_text(encoding="utf-8"))
    site_news_pool.validate(pool)
    by_id = {item["id"]: item for item in pool["items"]}
    changes = []
    for brief in rows:
        item = by_id.get(brief["pool_id"])
        if not item or item["sequence"] != brief["pool_sequence"]:
            raise ValueError("Approved brief is missing the original pool record")
        if not (root / "briefs" / brief["slug"] / "index.html").is_file():
            raise ValueError("Unrendered brief; pool stays untouched")
        if item["status"] == "approved" and item["article_id"] == brief["slug"]:
            continue
        owned_short_claim = (item["status"] == "in_review" and
                             item["note"].startswith(
                                 "SHORT_EDITOR claim=short; pool_id=" + brief["pool_id"]))
        if item["status"] != "queued" and not owned_short_claim:
            raise ValueError("Refusing to overwrite a foreign reserved/processed pool item")
        suffix = "Опубликовано в «Новости коротко»: https://iipike.ru/briefs/" + brief["slug"] + "/"
        note = (item["note"].rstrip() + chr(10) + suffix).strip()
        if len(note) > 1500:
            raise ValueError("Pool note too long; needs manual review")
        item["status"] = "approved"
        item["article_id"] = brief["slug"]
        item["closed_at"] = brief["published_at_utc"]
        item["note"] = note
        changes.append(brief["slug"])
    site_news_pool.validate(pool)
    return pool, changes

def main():
    arg = argparse.ArgumentParser()
    arg.add_argument("--write", action="store_true")
    opts = arg.parse_args()
    pool, changed = synchronized(ROOT)
    if opts.write and changed:
        (ROOT / "data/site_news_pool.json").write_text(
            json.dumps(pool, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8"
        )
    print("Raw pool reconciled:", len(changed), changed)

if __name__ == "__main__":
    main()
