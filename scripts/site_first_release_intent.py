#!/usr/bin/env python3
"""Verify an explicitly requested emergency site release from a GitHub push.

This file ONLY validates a release instruction and emits GitHub Actions outputs.
It never publishes, and does not accept an untrusted PR or cron as emergency
authorization. Every request must be a fresh, standalone change to one control
file on the protected main branch.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess

from scripts.site_first_release_pr import STABLE_ID

REQUEST_PATH = ".github/site-first-urgent-request.json"
KICK_PATH = ".github/site-first-queue-kick.txt"
URGENT_MARKER = "[hpii-urgent-release]"
QUEUE_MARKER = "[hpii-queue-kick]"
REPO = "AfterDark1000/iipike-site"
MAX_AGE = dt.timedelta(minutes=45)
MAX_FUTURE_SKEW = dt.timedelta(minutes=3)


def run_git(*args):
    return subprocess.run(["git", *args], check=True, text=True,
                          capture_output=True).stdout.strip()


def verify_push_intent(event, *, now=None, git_cmd=run_git, read=Path.read_text):
    """Return verified mode and exact story ID; raise on any ambiguity."""
    if event.get("repository", {}).get("full_name") != REPO:
        raise ValueError("Unexpected repository in push event")
    if event.get("ref") != "refs/heads/main" or event.get("deleted"):
        raise ValueError("Emergency releases only accept a main branch push")
    before, after = event.get("before", ""), event.get("after", "")
    if (not re.fullmatch("[a-f0-9]{40}", before)
            or not re.fullmatch("[a-f0-9]{40}", after)
            or before == "0" * 40):
        raise ValueError("Invalid before/after Git commit IDs")
    if git_cmd("rev-parse", "HEAD") != after:
        raise ValueError("Current checkout is not exactly the pushed commit")
    changes = git_cmd("diff", "--name-only", before, after).splitlines()
    message = event.get("head_commit", {}).get("message", "")
    if changes == [KICK_PATH] and QUEUE_MARKER in message:
        return "queue", ""
    if changes != [REQUEST_PATH]:
        raise ValueError("Not a standalone urgent request or scheduled queue kick")
    match = re.fullmatch(r"hpii: \[hpii-urgent-release\] ([a-z0-9-]{1,72})", message)
    if not match:
        raise ValueError("Explicit urgent marker and exact ID required")
    sid = match.group(1)
    if not STABLE_ID.fullmatch(sid) or len(sid) > 72:
        raise ValueError("Invalid emergency story ID")
    raw = read(Path(REQUEST_PATH), encoding="utf-8")
    if len(raw) > 2048:
        raise ValueError("Emergency request is too large")
    req = json.loads(raw)
    if (not isinstance(req, dict)
            or set(req) != {"story_id", "urgent", "requested_at"}
            or req["story_id"] != sid
            or req["urgent"] is not True):
        raise ValueError("Emergency request must match commit ID and urgent=true")
    timestamp = req["requested_at"]
    if not isinstance(timestamp, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", timestamp):
        raise ValueError("Emergency request requires UTC requested_at timestamp")
    requested_at = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    now = now or dt.datetime.now(dt.timezone.utc)
    age = now.astimezone(dt.timezone.utc) - requested_at
    if not -MAX_FUTURE_SKEW <= age <= MAX_AGE:
        raise ValueError("Urgent release authorization expired or future-dated")
    return "urgent", sid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    mode, sid = "", ""
    if os.environ.get("GITHUB_EVENT_NAME") == "push":
        if os.environ.get("GITHUB_REPOSITORY") != REPO:
            raise ValueError("Unexpected GitHub repository")
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        mode, sid = verify_push_intent(event)
    with open(args.output, "a", encoding="utf-8") as out:
        out.write("mode=" + mode + "\n")
        out.write("story_id=" + sid + "\n")
        out.write("urgent=" + ("true" if mode == "urgent" else "false") + "\n")
    print("HPII_QUEUE_INTENT:", mode or "cron-or-manual", sid)


if __name__ == "__main__":
    main()
