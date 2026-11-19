#!/usr/bin/env python3
"""Release at most one previously owner-approved short news story per 15-minute slot.

Only the separate, verified published-manifest makes a brief public.
No unattended approval, and no edits to the full hourly article publisher.
"""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import build_briefs

RELEASED = Path("data/briefs/released.json")
LOCAL_TZ = ZoneInfo("Asia/Yekaterinburg")
MIN_GAP = timedelta(minutes=15)


def releases(root, approved_rows=None):
    path = Path(root) / RELEASED
    doc = json.loads(path.read_text(encoding="utf-8"))
    if (type(doc) is not dict or set(doc) != {"schema_version", "note", "items"}
            or doc["schema_version"] != 1 or not isinstance(doc["note"], str)
            or not isinstance(doc["items"], list)):
        raise ValueError("Invalid released brief manifest")
    allowed = {x["slug"]: x for x in (approved_rows if approved_rows is not None
                                     else build_briefs.validated(root))}
    seen, result = set(), []
    for row in doc["items"]:
        if (type(row) is not dict or
                set(row) != {"slug", "published_at_utc"} or
                not isinstance(row["slug"], str) or row["slug"] not in allowed
                or row["slug"] in seen):
            raise ValueError("Unapproved, duplicate or invalid brief release")
        seen.add(row["slug"])
        release_time = build_briefs.parse_time(row["published_at_utc"])
        approved_time = build_briefs.parse_time(allowed[row["slug"]]["approved_at_utc"])
        if release_time < approved_time:
            raise ValueError("Brief site release predates approval")
        result.append((row["slug"], release_time))
    return doc, result


def release_one(root, *, now=None):
    root = Path(root)
    now = now or datetime.now(timezone.utc).replace(microsecond=0)
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("Timezone-aware now required")
    now = now.astimezone(timezone.utc).replace(microsecond=0)
    approved = build_briefs.validated(root)
    doc, released = releases(root, approved)
    # Site-first's editorial night window: no 01:00–06:59 local releases.
    if 1 <= now.astimezone(LOCAL_TZ).hour < 7:
        return doc, None, "night_pause"
    # Guard the entire quarter-hour even when Actions starts late.
    quarter = now.replace(minute=(now.minute // 15) * 15, second=0)
    if any(p >= quarter for _, p in released):
        return doc, None, "slot_already_used"
    if released and now - max(p for _, p in released) < MIN_GAP:
        return doc, None, "minimum_gap"
    released_ids = {slug for slug, _ in released}
    pending = sorted((r for r in approved if r["slug"] not in released_ids),
                     key=lambda r:(r["approved_at_utc"], r["pool_sequence"], r["slug"]))
    if not pending:
        return doc, None, "nothing_approved"
    target = pending[0]
    updated = copy.deepcopy(doc)
    updated["items"].append({
        "slug": target["slug"],
        "published_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ")
    })
    releases_test = {x["slug"] for x in updated["items"]}
    if len(releases_test) != len(updated["items"]):
        raise ValueError("Duplicate release attempt")
    return updated, target["slug"], "released_one"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--write", action="store_true")
    args = p.parse_args()
    updated, slug, reason = release_one(ROOT)
    if args.write and slug:
        (ROOT / RELEASED).write_text(
            json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    print(json.dumps({"release": slug, "status": reason, "wrote": bool(args.write and slug)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
