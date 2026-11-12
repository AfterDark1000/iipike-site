#!/usr/bin/env python3
"""One-off, bounded recovery: release the approved queue in order THROUGH Gemini.

This is NOT a general publisher. The fixed scope is the backlog preceding
"google-gemini-for-healthcare-20261110" on 2026-11-12. It reuses the
production publisher, validates every single article, never merges multiple
stories, and stops immediately after that exact article is published.
"""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.site_first_release_pr import GH_REPO, git, release_one, safe_git_blob_at
from scripts.site_publication_queue import (
    SITE_TZ, MAIN_REF, QUEUE_REF, in_quiet_hours,
    latest_site_first_publication, ready_items, without_published_collisions,
)

TARGET = "google-gemini-for-healthcare-20261110"
KICK = ".github/site-first-catchup-kick.txt"
MARKER = "[hpii-site-catchup-gemini]"
MIN_GAP = dt.timedelta(minutes=2)
MAX_ARTICLES = 9
# Safety cutoff. If the job starts/runs too late, ordinary queue takes over.
ENDS_AT = dt.datetime(2026, 11, 12, 16, 0, tzinfo=SITE_TZ)


def scope_before_target(pending, target=TARGET):
    """Only the due, ready candidates ahead of and including exact target."""
    ids = [item["id"] for item in pending]
    if target not in ids:
        raise ValueError("Gemini target absent from eligible queue; no recovery")
    chosen = pending[:ids.index(target) + 1]
    if len(chosen) > MAX_ARTICLES:
        raise ValueError("Recovery scope grew beyond nine approved stories")
    return chosen


def verify_authorized_kick():
    """Disallow direct, accidental or unrelated commits from mass releasing."""
    if (os.getenv("GITHUB_REPOSITORY") != GH_REPO
            or os.getenv("GITHUB_REF") != "refs/heads/main"
            or os.getenv("GITHUB_EVENT_NAME") != "push"
            or os.getenv("HPII_SITE_FIRST_CATCHUP") != "1"):
        raise ValueError("Recovery requires explicit authorized repository push")
    commit = git("log", "-1", "--format=%s").stdout.strip()
    files = git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.splitlines()
    if MARKER not in commit or files != [KICK]:
        raise ValueError("Recovery only accepts the exact one-file kick with marker")


def main():
    verify_authorized_kick()
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    released = []
    for number in range(MAX_ARTICLES):
        now = dt.datetime.now(dt.timezone.utc)
        if now >= ENDS_AT.astimezone(dt.timezone.utc) or in_quiet_hours(now):
            raise ValueError("Recovery aborted at hard deadline or quiet hours")
        git("fetch", "origin", "main", "editorial-intake")
        source_ref = git("rev-parse", QUEUE_REF).stdout.strip()
        live = json.loads(safe_git_blob_at(MAIN_REF, "news.json"))
        if any(row.get("id") == TARGET for row in live):
            print("CATCHUP_TARGET_ALREADY_PUBLISHED: " + TARGET, flush=True)
            return
        pending = without_published_collisions(
            ready_items(source_ref), live, source_ref=source_ref)
        scoped = scope_before_target(pending)
        item = scoped[0]
        last = latest_site_first_publication(live)
        now = dt.datetime.now(dt.timezone.utc)
        if last and now < last + MIN_GAP:
            remaining = (last + MIN_GAP - now).total_seconds()
            print(f"CATCHUP_SPACING_WAIT_SECONDS: {remaining:.0f}", flush=True)
            time.sleep(remaining + 1)
            now = dt.datetime.now(dt.timezone.utc)
        if now >= ENDS_AT.astimezone(dt.timezone.utc) or in_quiet_hours(now):
            raise ValueError("Recovery aborted at deadline before next release")
        if any(row.get("id") == item["id"] for row in live):
            raise ValueError("Unexpected already-published item during recovery")
        print(f"CATCHUP_RELEASE: {number + 1}/{len(scoped) + number} {item['id']}",
              flush=True)
        outcome = release_one(item["id"], source_ref)
        if outcome != "auto_published_rebuild_requested":
            raise ValueError("Recovery stopped; unconfirmed release: " + str(outcome))
        released.append(item["id"])
        print("CATCHUP_PAGES_REBUILD_REQUESTED: " + item["id"], flush=True)
        if item["id"] == TARGET:
            print("CATCHUP_COMPLETE_TARGET_PUBLISHED: " + TARGET, flush=True)
            print("CATCHUP_RELEASED_IDS: " + json.dumps(released), flush=True)
            return
    raise ValueError("Recovery exhausted maximum scope without target publication")


if __name__ == "__main__":
    main()
