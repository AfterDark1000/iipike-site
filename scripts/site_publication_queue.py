#!/usr/bin/env python3
"""Private, hourly-spaced HPII site-first publication queue.

The approved article and original cover remain ONLY on editorial-intake
until selected for a public release. A GitHub cron examines the private
production branch metadata and publishes at most ONE due story per run.

No pages, RSS entries, sitemap URLs or news.json rows are created by
the mere delivery of a cover. Publication is an explicit scheduled step.
"""
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.site_first_release_pr import (
    COVER, IMAGE_EXTS, STABLE_ID, STORY, GH_REPO,
    exists_at, git, release_one, safe_git_blob_at,
)

SITE_TZ = ZoneInfo("Asia/Yekaterinburg")
INTERVAL = dt.timedelta(minutes=60)
QUEUE_REF = "origin/editorial-intake"
MAIN_REF = "origin/main"


def parse_slot(value):
    """Accept exactly an explicit Ekaterinburg local-time publication slot."""
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+05:00", value):
        raise ValueError("site_publish_at must be YYYY-MM-DDTHH:MM:SS+05:00")
    value_dt = dt.datetime.fromisoformat(value)
    if value_dt.utcoffset() != dt.timedelta(hours=5):
        raise ValueError("site_publish_at is not in Yekaterinburg time")
    return value_dt.astimezone(dt.timezone.utc)


def _utc(value):
    stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.utcoffset() is None:
        raise ValueError("Missing timezone offset")
    return stamp.astimezone(dt.timezone.utc)


def _last_change(ref, path):
    result = git("log", "-1", "--format=%cI", ref, "--", path).stdout.strip()
    if not result:
        raise ValueError("Could not determine last commit of " + path)
    return _utc(result)


def latest_site_first_publication(rows, *, main_ref=MAIN_REF):
    """Ignore historical Dzen dates; only real site-first issues set spacing."""
    latest = None
    for row in rows:
        sid = row.get("id", "")
        if not isinstance(sid, str) or not STABLE_ID.fullmatch(sid):
            continue
        # The original historical imports have content/approved sources,
        # but only new site-first stories have an editorial_inbox source in main.
        if not exists_at(main_ref, f"editorial_inbox/stories/{sid}.json"):
            continue
        stamp = row.get("published_at_utc")
        if not isinstance(stamp, str) or not stamp:
            continue
        time = _utc(stamp)
        if latest is None or time > latest:
            latest = time
    return latest


def ready_items(ref=QUEUE_REF, *, main_ref=MAIN_REF):
    """Read the Git tree, not webhook file arrays or arbitrary user-supplied IDs."""
    tree = git("ls-tree", "-r", "--name-only", ref, "--",
               "editorial_inbox/stories", "editorial_inbox/covers").stdout
    stories, covers = set(), {}
    for path in tree.splitlines():
        st = STORY.fullmatch(path)
        im = COVER.fullmatch(path)
        if st:
            stories.add(st[1])
        elif im:
            covers.setdefault(im[1], []).append(path)
    ready = []
    for sid in sorted(stories):
        source = f"editorial_inbox/stories/{sid}.json"
        if exists_at(main_ref, f"articles/{sid}/index.html"):
            continue
        matched = covers.get(sid, [])
        if not matched:
            print("AWAITING_COVER:", sid, flush=True)
            continue
        if len(matched) != 1:
            raise ValueError("Multiple covers for " + sid)
        raw = safe_git_blob_at(ref, source)
        if len(raw) > 128_000:
            raise ValueError("Overlarge pending editorial story: " + sid)
        story = json.loads(raw)
        if (not isinstance(story, dict) or story.get("id") != sid or
                story.get("status") != "editor_approved" or
                story.get("approved_by") != "human_editor"):
            raise ValueError("Unapproved or inconsistent pending story: " + sid)
        earliest = parse_slot(story["site_publish_at"]) if "site_publish_at" in story else None
        ready_at = max(_last_change(ref, source), _last_change(ref, matched[0]))
        ready.append({
            "id": sid, "ready_at": ready_at, "not_before": earliest,
            "cover": matched[0],
        })
    return sorted(ready, key=lambda x: (x["ready_at"], x["id"]))


def select_one(items, rows, now, *, target=None, urgent=False):
    if now.tzinfo is None:
        raise ValueError("Scheduled check needs an offset-aware time")
    now = now.astimezone(dt.timezone.utc)
    if urgent and not target:
        raise ValueError("Urgent override requires an exact editorial story ID")
    if target and (not isinstance(target, str) or len(target) > 72 or
                   not STABLE_ID.fullmatch(target)):
        raise ValueError("Invalid exact story ID")
    if target and not any(item["id"] == target for item in items):
        raise ValueError("Requested story is not approved, cover-ready and unpublished")
    last = latest_site_first_publication(rows)
    if not urgent and last and now < last + INTERVAL:
        print("SPACING_WAIT until", (last + INTERVAL).isoformat(), flush=True)
        return None
    for item in items:
        if target and item["id"] != target:
            continue
        if not urgent and item["not_before"] and now < item["not_before"]:
            print("FUTURE_SLOT:", item["id"], item["not_before"].isoformat(), flush=True)
            continue
        if not urgent and now < item["ready_at"]:
            print("COVER_COMMIT_NOT_YET_DUE:", item["id"], flush=True)
            continue
        return item
    return None


def main():
    if os.environ.get("GITHUB_REPOSITORY") != GH_REPO:
        raise ValueError("Unexpected repository for scheduled site release")
    # Only this dedicated workflow has permission to publish. A cover
    # event is read-only and cannot call this command with this token.
    if os.environ.get("HPII_SITE_FIRST_SCHEDULER") != "1" or \
            os.environ.get("HPII_SITE_FIRST_AUTOPUBLISH") != "1":
        raise ValueError("Scheduled publisher is not explicitly authorized")
    target = os.environ.get("HPII_TARGET_STORY_ID", "").strip() or None
    urgent = os.environ.get("HPII_URGENT_STORY", "false").lower() == "true"
    inspect_only = os.environ.get("HPII_QUEUE_INSPECT_ONLY", "false").lower() == "true"
    if inspect_only and os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise ValueError("Read-only inspection may only be selected manually")
    if urgent and inspect_only:
        raise ValueError("Cannot combine urgent release and read-only inspection")
    if urgent and os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        if (os.environ.get("GITHUB_EVENT_NAME") != "push" or
                os.environ.get("HPII_VERIFIED_PUSH_URGENT") != "true" or
                not target):
            raise ValueError(
                "Urgency override requires manual workflow dispatch or "
                "a verified owner-authored, exact-ID urgent push")
    git("fetch", "origin", "editorial-intake", "main")
    source_ref = git("rev-parse", QUEUE_REF).stdout.strip()
    rows = json.loads(Path("news.json").read_text(encoding="utf-8"))
    # Refresh the live production index, not the potentially stale local main.
    live = json.loads(safe_git_blob_at(MAIN_REF, "news.json"))
    pending = ready_items(source_ref)
    print("QUEUE_READY:", len(pending), "IDs:",
          [x["id"] for x in pending], flush=True)
    if inspect_only:
        print("INSPECTION_ONLY: queue checked, no release allowed", flush=True)
        return
    item = select_one(pending, live, dt.datetime.now(dt.timezone.utc),
                      target=target, urgent=urgent)
    if not item:
        print("NO_DUE_STORY: No article released", flush=True)
        return
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    print("SCHEDULED_RELEASE:", item["id"], "urgent=" + str(urgent), flush=True)
    outcome = release_one(item["id"], source_ref)
    if outcome != "auto_published_rebuild_requested":
        raise ValueError("Scheduled release not confirmed: " + str(outcome))
    print("ONE_RELEASE_REQUESTED:", item["id"], flush=True)
    print("NOTE: Public page requires a successful subsequent GitHub Pages deployment",
          flush=True)


if __name__ == "__main__":
    main()
