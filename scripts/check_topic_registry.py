#!/usr/bin/env python3
"""Audit an editor-created topic extension and prevent changing old topic URLs.

Usage:
  python3 scripts/check_topic_registry.py
  python3 scripts/check_topic_registry.py --base-sha <PR base commit SHA>
The PR check is read-only. A successful new topic still requires green CI
and an explicit editor-initiated PR merge; never merge untested changes.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.site_topic_registry import load_manifest, require_append_only
from scripts.site_topics import TOPICS, BUILTIN_TOPICS

PATH = "data/topic_extensions.json"


def check(base_sha=None):
    new = load_manifest(ROOT / PATH)
    if len(TOPICS) != len(BUILTIN_TOPICS) + len(new["topics"]):
        raise ValueError("Topic registry and active vocabulary disagree")
    if base_sha:
        if not re.fullmatch("[0-9a-f]{40}", base_sha):
            raise ValueError("Unsafe PR base SHA")
        res = subprocess.run(
            ["git", "show", base_sha + ":" + PATH],
            cwd=ROOT, check=False, capture_output=True, text=True, timeout=15,
        )
        if res.returncode:
            # First introduction only: allow absent file but not arbitrary
            # failed Git operations or a different existing registry.
            baseline = subprocess.run(
                ["git", "cat-file", "-e", base_sha + "^{commit}"],
                cwd=ROOT, capture_output=True, text=True,
            )
            if baseline.returncode:
                raise ValueError("PR base commit cannot be validated")
            listed = subprocess.run(
                ["git", "ls-tree", base_sha, "--", PATH],
                cwd=ROOT, capture_output=True, text=True,
            )
            if listed.returncode or listed.stdout.strip():
                raise ValueError("Unable to verify old topic registry")
            old = {"schema_version": 1, "topics": []}
        else:
            old = json.loads(res.stdout)
        added = require_append_only(old, new)
        print("Topic registry append-only check passed; new topics:", added)
    print("Validated active topic keys:", len(TOPICS))
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-sha")
    args = parser.parse_args()
    try:
        check(args.base_sha)
    except (ValueError, OSError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        sys.exit("Topic registry rejected: " + str(e))
