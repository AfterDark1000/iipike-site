#!/usr/bin/env python3
"""Read-only validator for the HPII chief copyeditor pilot.

Compares the agent's proposed *text-only* changes against the original
auto_draft Git blob. Does not modify drafts, approvals, covers or publications.
"""
import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.auto_editor_workbench import validate_draft
from scripts.site_news_pool import utc_time

FIELDS = ("title", "dzen_title", "summary", "article_markdown",
          "threads_text", "x_text", "vk_title", "vk_summary")
STATUSES = {"ready_for_comparison", "needs_editor_attention"}
ARTICLE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
NAME = re.compile(r"(?P<id>[a-z0-9]+(?:-[a-z0-9]+)*)-r(?P<rev>[1-9]\d*)-v(?P<version>[1-9]\d*)\.json\Z")
NUMBER = re.compile(r"\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?%?")
URL = re.compile(r"https?://[^\s\])>]+")
HANDLE = re.compile(r"(?<![\w])@[A-Za-z][\w.]{1,30}")
QUOTE = re.compile(r"^>\s.+$", re.MULTILINE)


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True,
                          capture_output=True).stdout


def blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def values(text, regex):
    return Counter(regex.findall(text))


def validate(source_bytes, candidate, *, filename=None):
    if not isinstance(candidate, dict) or set(candidate) != {
        "schema_version", "article_id", "source_revision", "source_updated_at",
        "source_draft_blob_sha", "copyedit_version", "status", "created_at",
        "worker", "original_text", "edited_text", "change_log", "editor_flags"
    }:
        raise ValueError("Invalid copyeditor candidate schema")
    source = json.loads(source_bytes.decode("utf-8"))
    sid = candidate["article_id"]
    if not isinstance(sid, str) or not ARTICLE_ID.fullmatch(sid):
        raise ValueError("Invalid article ID")
    if source["article_id"] != sid or source["status"] != "ready_for_review":
        raise ValueError("Copyeditor requires exact ready_for_review original")
    if (candidate["schema_version"] != 1 or
            candidate["worker"] != "hpii-chief-copyeditor" or
            candidate["source_revision"] != source["revision"] or
            candidate["source_updated_at"] != source["updated_at"] or
            candidate["source_draft_blob_sha"] != blob_sha(source_bytes)):
        raise ValueError("Original draft identity, revision or Git blob mismatch")
    version = candidate["copyedit_version"]
    if type(version) is not int or version < 1 or version > 5:
        raise ValueError("Invalid copyedit version")
    if filename and filename != f"{sid}-r{source['revision']}-v{version}.json":
        raise ValueError("Copyedit filename does not match original and version")
    if candidate["status"] not in STATUSES:
        raise ValueError("Invalid candidate status")
    created = utc_time(candidate["created_at"])
    source_time = utc_time(source["updated_at"])
    if created < source_time:
        raise ValueError("Copyedit cannot predate its source")
    original = candidate["original_text"]
    edited = candidate["edited_text"]
    if (not isinstance(original, dict) or not isinstance(edited, dict) or
            set(original) != set(FIELDS) or set(edited) != set(FIELDS) or
            not all(isinstance(x, str) for x in list(original.values()) + list(edited.values()))):
        raise ValueError("Copyeditor may touch only the eight named text fields")
    for field in FIELDS:
        if original[field] != source["content"][field]:
            raise ValueError("Original copy is not an exact source snapshot: " + field)
    for field in FIELDS:
        if not edited[field].strip() or len(edited[field]) > 50000:
            raise ValueError("Empty or oversized edited field: " + field)
    if edited["title"] != edited["dzen_title"]:
        raise ValueError("Site and Dzen headlines must match")
    if not any(original[field] != edited[field] for field in FIELDS):
        raise ValueError("No actual copyediting changes")
    for field in FIELDS:
        if values(original[field], URL) != values(edited[field], URL):
            raise ValueError("Changed or missing URL in " + field)
        if values(original[field], HANDLE) != values(edited[field], HANDLE):
            raise ValueError("Changed social account handle in " + field)
        if values(original[field], NUMBER) != values(edited[field], NUMBER):
            raise ValueError("Changed numerical token in " + field)
    if values(original["article_markdown"], QUOTE) != values(edited["article_markdown"], QUOTE):
        raise ValueError("A source quotation or its Markdown prefix was altered")
    log = candidate["change_log"]
    flags = candidate["editor_flags"]
    if (not isinstance(log, list) or not 1 <= len(log) <= 20 or
            not all(isinstance(v, str) and 5 <= len(v) <= 400 for v in log) or
            not isinstance(flags, list) or len(flags) > 20 or
            not all(isinstance(v, str) and 5 <= len(v) <= 400 for v in flags)):
        raise ValueError("Invalid changes or editor flags")
    if candidate["status"] == "needs_editor_attention" and not flags:
        raise ValueError("Escalated copyedit must contain a specific flag")
    if candidate["status"] == "ready_for_comparison" and flags:
        raise ValueError("Flagged copyedit cannot be presented as clean")
    updated = copy.deepcopy(source)
    updated["content"].update(edited)
    receipt = {"status": "reserved", "request": source["request"],
               "pool_id": source["pool_id"], "pool_sequence": source["pool_sequence"],
               "article_id": sid}
    validate_draft(updated, receipt)
    return {"article_id": sid, "revision": source["revision"],
            "version": version, "status": candidate["status"]}


def verify_tree(ref):
    folder = "editorial_inbox/auto_copyedits/"
    listing = git("ls-tree", "-r", "--name-only", ref, "--", folder).decode()
    results = []
    for path in listing.splitlines():
        if path == folder + "README.md":
            continue
        if not path.startswith(folder) or not NAME.fullmatch(path[len(folder):]):
            raise ValueError("Unexpected copyedit candidate path: " + path)
        raw = git("show", ref + ":" + path)
        if len(raw) > 262144:
            raise ValueError("Oversized copyedit candidate: " + path)
        candidate = json.loads(raw)
        # Git history preserves old source blobs even if a later human
        # revision changes the current auto_draft: audit remains possible.
        sha = candidate.get("source_draft_blob_sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Invalid original Git blob SHA")
        original = git("cat-file", "blob", sha)
        results.append(validate(original, candidate, filename=path[len(folder):]))
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path)
    ap.add_argument("--candidate", type=Path)
    ap.add_argument("--verify-tree", action="store_true")
    ap.add_argument("--ref", default="origin/editorial-intake")
    args = ap.parse_args()
    if args.verify_tree:
        result = verify_tree(args.ref)
    elif args.source and args.candidate:
        result = validate(args.source.read_bytes(),
                          json.loads(args.candidate.read_text(encoding="utf-8")),
                          filename=args.candidate.name)
    else:
        ap.error("Pass --verify-tree or --source and --candidate")
    print(json.dumps({"validated": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
