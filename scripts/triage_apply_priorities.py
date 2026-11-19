#!/usr/bin/env python3
"""Apply ONLY approved hot priority promotions after validating entire live pool.

Does not alter review status, closure, article IDs, notes or content; no publication.
"""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import site_news_pool, editorial_routing

SOURCE = Path("data/editorial_triage/approved_2026-11-19.json")
POOL = Path("data/site_news_pool.json")


def promote(pool, approved):
    site_news_pool.validate(pool)
    highs = approved.get("new_high_proposed")
    if (not isinstance(highs, list) or len(highs) != 7 or
            len(set(highs)) != 7 or
            any(type(n) is not int for n in highs)):
        raise ValueError("Invalid exact approved high list")
    if not set(highs) <= set(approved["decision_groups"]["hot"]):
        raise ValueError("Approved high promotions not in hot group")
    updated = copy.deepcopy(pool)
    indexed = {i["sequence"]: i for i in updated["items"]}
    promoted, already, held = [], [], []
    for n in highs:
        item = indexed.get(n)
        if not item:
            raise ValueError(f"Missing promoted candidate #{n}")
        if item["priority"] == "high":
            already.append(n)
        elif item["status"] == "queued":
            item["priority"] = "high"
            promoted.append(n)
        else:
            # A concurrent human reservation is never overwritten.
            held.append({"sequence": n, "status": item["status"]})
    site_news_pool.validate(updated)
    return updated, {"promoted": promoted, "already_high": already, "unmodified_busy": held}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    pool_file = ROOT / POOL
    pool = json.loads(pool_file.read_text(encoding="utf-8"))
    editorial_routing.load_routes(pool, root=ROOT, require_all=True)
    approved = json.loads((ROOT / SOURCE).read_text(encoding="utf-8"))
    updated, report = promote(pool, approved)
    if args.write and updated != pool:
        pool_file.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
