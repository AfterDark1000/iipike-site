#!/usr/bin/env python3
"""Isolate invalid approved articles before site-first publication.

A broken article gets a durable editorial-only error marker; it is NOT
deleted or moved. Changing the source story/cover/inline image or the
publisher validation code automatically invalidates the marker.
Global publishing, GitHub, deployment and test failures are never
classified as article errors by this module.
"""
import base64
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from scripts.site_first_release_pr import GH_REPO, STABLE_ID, exists_at, git, safe_git_blob_at
from scripts.site_rich_text import markdown_to_blocks, IMAGE_SOURCE
from scripts.site_first_inbox import stage

PREFIX = "editorial_inbox/release_errors/"
CODE_PATHS = ("scripts/site_first_inbox.py", "scripts/publish_approved_article.py")
MAX_REASON = 400


def marker_path(sid):
    if not STABLE_ID.fullmatch(sid) or len(sid) > 72:
        raise ValueError("Invalid release-error article ID")
    return PREFIX + sid + ".json"


def story_paths(ref, item):
    sid = item["id"]
    story = "editorial_inbox/stories/" + sid + ".json"
    cover = item["cover"]
    data = json.loads(safe_git_blob_at(ref, story))
    if not isinstance(data, dict) or data.get("id") != sid:
        raise ValueError("Article ID differs from its editorial path")
    blocks = (markdown_to_blocks(data["article_markdown"]) if
              "article_markdown" in data else data.get("paragraphs", []))
    if not isinstance(blocks, list):
        raise ValueError("Editorial blocks must form a list")
    illustrations = []
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError("Malformed editorial block")
        if block.get("type") != "image":
            continue
        src = block.get("src", "")
        match = IMAGE_SOURCE.fullmatch(src)
        if match is None or match.group("story") != sid:
            raise ValueError("Invalid article-scoped illustration reference")
        illustrations.append("editorial_inbox/" + src)
    return [story, cover, *dict.fromkeys(illustrations)]


def content_fingerprint(ref, item, *, main_ref="origin/main"):
    """Fingerprint exact content and validator versions, not changing Git HEAD."""
    parts = []
    sid = item["id"]
    # Even malformed JSON/Markdown must be fingerprintable: the source blob
    # and cover are always enough to identify the editor's original version.
    paths = ["editorial_inbox/stories/" + sid + ".json", item["cover"]]
    try:
        paths.extend(path for path in story_paths(ref, item) if path not in paths)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        pass
    for path in paths:
        result = git("rev-parse", ref + ":" + path, check=False)
        parts.append(path + ":" + (result.stdout.strip() if result.returncode == 0
                                   else "<missing>"))
    for path in CODE_PATHS:
        blob = git("rev-parse", main_ref + ":" + path).stdout.strip()
        parts.append(path + ":" + blob)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def existing_error(ref, item, *, main_ref="origin/main"):
    path = marker_path(item["id"])
    if not exists_at(ref, path):
        return None
    record = json.loads(safe_git_blob_at(ref, path))
    if (record.get("id") == item["id"]
            and record.get("status") == "blocked_article_validation"
            and record.get("fingerprint") ==
            content_fingerprint(ref, item, main_ref=main_ref)):
        return record
    return None


def copy_blob(ref, path, root):
    """Copy the exact binary Git blob to a temporary preflight tree."""
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as out:
        subprocess.run(["git", "show", ref + ":" + path],
                       stdout=out, stderr=subprocess.PIPE, check=True)


def preflight_article(ref, item, live):
    """Run real editorial text, image and crosslink validation without publishing."""
    with tempfile.TemporaryDirectory(prefix="hpii-preflight-") as tmp:
        root = Path(tmp)
        (root / "news.json").write_text(
            json.dumps(live, ensure_ascii=False), encoding="utf-8")
        for path in story_paths(ref, item):
            copy_blob(ref, path, root)
        result = stage(root, item["id"], apply=False)
        if result is None:
            raise ValueError("Article is incomplete despite ready-queue status")
    return True


def record_article_error(ref, item, error, *, main_ref="origin/main"):
    """Persist a per-story error, with optimistic SHA guard, in editorial-intake.

    Only called after article-specific preflight validation fails. If recording
    fails, propagate the error; the publisher must NOT silently skip it.
    """
    sid = item["id"]
    path = marker_path(sid)
    reason = " ".join(str(error).split())[:MAX_REASON]
    payload = {
        "id": sid, "status": "blocked_article_validation",
        "reason": reason, "fingerprint":
            content_fingerprint(ref, item, main_ref=main_ref),
        "blocked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    args = ["gh", "api", "-X", "PUT",
            "repos/" + GH_REPO + "/contents/" + path,
            "-f", "branch=editorial-intake",
            "-f", "message=watchdog: quarantine invalid site article " + sid,
            "-f", "content=" + base64.b64encode(
                (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            ).decode("ascii")]
    if exists_at(ref, path):
        sha = git("rev-parse", ref + ":" + path).stdout.strip()
        args.extend(["-f", "sha=" + sha])
    subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return payload
