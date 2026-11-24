#!/usr/bin/env python3
"""Read-only bridge checker: copyeditor flags -> autonomous editor acknowledgements.

No changes to drafts, publication, decisions or pool are performed here.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

from scripts.check_auto_copyeditor_pilot import blob_sha
from scripts.site_news_pool import utc_time

ROOT = Path(__file__).resolve().parents[1]
COPIES = "editorial_inbox/auto_copyedits"
RESPONSES = "editorial_inbox/auto_copyedit_responses"
DRAFTS = "editorial_inbox/auto_drafts"
DECISIONS = "editorial_inbox/auto_decisions"
COPY_NAME = re.compile(r"([a-z0-9]+(?:-[a-z0-9]+)*)-r([1-9]\d*)-v([1-9]\d*)\.json\Z")
SHA = re.compile(r"[a-f0-9]{40}\Z")
RESPONSE_STATES = {"revised", "needs_human_decision"}
EXPECTED = {
    "schema_version", "article_id", "source_revision", "copyedit_version",
    "source_draft_blob_sha", "copyedit_blob_sha", "status", "result_revision",
    "result_draft_blob_sha", "note", "checked_sources", "worker", "created_at",
}


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True,
                          capture_output=True).stdout


def read_at(ref, path):
    try:
        return git("show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return None


def files_at(ref, folder):
    return [
        p for p in git("ls-tree", "-r", "--name-only", ref, "--", folder + "/")
        .decode().splitlines() if p.endswith(".json")
    ]


def validate_response(raw_copy, response, source_raw, result_raw=None, *, filename=None):
    """Validate durable answer attached to an exact immutable copyedit and draft."""
    copyedit = json.loads(raw_copy.decode("utf-8"))
    source = json.loads(source_raw.decode("utf-8"))
    if not isinstance(response, dict) or set(response) != EXPECTED:
        raise ValueError("Invalid feedback response schema")
    if type(response["schema_version"]) is not int or response["schema_version"] != 1:
        raise ValueError("Invalid feedback schema_version")
    if response["worker"] != "hpii-auto-editor":
        raise ValueError("Response must come from the autonomous editor")
    ident = response["article_id"]
    rev = response["source_revision"]
    version = response["copyedit_version"]
    if (type(ident) is not str or type(rev) is not int or type(version) is not int
            or rev < 1 or version < 1):
        raise ValueError("Invalid identity")
    name = f"{ident}-r{rev}-v{version}.json"
    if not COPY_NAME.fullmatch(name) or (filename is not None and filename != name):
        raise ValueError("Invalid response filename")
    if (copyedit.get("status") != "needs_editor_attention"
            or copyedit.get("article_id") != ident
            or copyedit.get("source_revision") != rev
            or copyedit.get("copyedit_version") != version
            or source.get("article_id") != ident
            or source.get("revision") != rev
            or source.get("status") != "ready_for_review"):
        raise ValueError("Copyedit is not a pending fact question about this draft")
    if (response["source_draft_blob_sha"] != copyedit.get("source_draft_blob_sha")
            or response["source_draft_blob_sha"] != blob_sha(source_raw)
            or response["copyedit_blob_sha"] != blob_sha(raw_copy)):
        raise ValueError("Feedback source SHA mismatch")
    utc_time(response["created_at"])
    if (not isinstance(response["note"], str)
            or not 20 <= len(response["note"].strip()) <= 1200
            or not isinstance(response["checked_sources"], list)
            or len(response["checked_sources"]) > 15
            or not all(isinstance(x, str) and 5 <= len(x) <= 800
                       for x in response["checked_sources"])):
        raise ValueError("Feedback needs specific explanation and checked sources")
    state = response["status"]
    if state not in RESPONSE_STATES:
        raise ValueError("Unknown response state")
    if state == "needs_human_decision":
        if response["result_revision"] is not None or response["result_draft_blob_sha"] is not None:
            raise ValueError("Human question must not pretend to have revised the draft")
        return {"article_id": ident, "status": state}
    result_rev = response["result_revision"]
    result_sha = response["result_draft_blob_sha"]
    if (type(result_rev) is not int or result_rev != rev + 1
            or type(result_sha) is not str or not SHA.fullmatch(result_sha)
            or result_raw is None or blob_sha(result_raw) != result_sha):
        raise ValueError("Revised response must bind the exact next draft revision blob")
    revised = json.loads(result_raw.decode("utf-8"))
    if (revised.get("article_id") != ident or revised.get("revision") != result_rev
            or revised.get("status") != "ready_for_review"
            or revised.get("pool_id") != source.get("pool_id")
            or revised.get("request") != source.get("request")):
        raise ValueError("Revised draft identity/status mismatch")
    marker = f"copyedit_feedback={name}; copyedit_sha={response['copyedit_blob_sha']}"
    if not any(marker in x for x in revised.get("editor_notes", []) if isinstance(x, str)):
        raise ValueError("Draft revision has no explicit copyeditor feedback marker")
    return {"article_id": ident, "status": state, "result_revision": result_rev}


def pending(ref):
    """List actionable fact flags; skip stale, answered and human-decided revisions."""
    answered = {p.rsplit("/", 1)[-1] for p in files_at(ref, RESPONSES)}
    output = []
    for path in files_at(ref, COPIES):
        name = path.rsplit("/", 1)[-1]
        if not COPY_NAME.fullmatch(name) or name in answered:
            continue
        raw = read_at(ref, path)
        if raw is None:
            continue
        item = json.loads(raw)
        if item.get("status") != "needs_editor_attention":
            continue
        ident, rev = item.get("article_id"), item.get("source_revision")
        if type(ident) is not str or type(rev) is not int:
            continue
        draft_raw = read_at(ref, f"{DRAFTS}/{ident}.json")
        if draft_raw is None or blob_sha(draft_raw) != item.get("source_draft_blob_sha"):
            continue
        draft = json.loads(draft_raw)
        if draft.get("revision") != rev or draft.get("status") != "ready_for_review":
            continue
        if read_at(ref, f"{DECISIONS}/{ident}-r{rev}.json") is not None:
            continue
        output.append({
            "copyedit": name, "copyedit_sha": blob_sha(raw), "article_id": ident,
            "pool_sequence": draft["pool_sequence"], "source_revision": rev,
            "source_draft_blob_sha": item["source_draft_blob_sha"],
            "editor_flags": item["editor_flags"]
        })
    return sorted(output, key=lambda x: (x["pool_sequence"], x["copyedit"]))


def verify_tree(ref):
    result = []
    for path in files_at(ref, RESPONSES):
        name = path.rsplit("/", 1)[-1]
        if not COPY_NAME.fullmatch(name):
            raise ValueError("Unexpected response filename: " + path)
        response = json.loads(read_at(ref, path))
        raw_copy = read_at(ref, f"{COPIES}/{name}")
        if raw_copy is None:
            raise ValueError("Missing original copyedit: " + name)
        source_sha = response.get("source_draft_blob_sha")
        if not isinstance(source_sha, str) or not SHA.fullmatch(source_sha):
            raise ValueError("Missing source draft SHA")
        source_raw = git("cat-file", "blob", source_sha)
        result_sha = response.get("result_draft_blob_sha")
        result_raw = git("cat-file", "blob", result_sha) if isinstance(result_sha, str) and SHA.fullmatch(result_sha) else None
        result.append(validate_response(raw_copy, response, source_raw, result_raw, filename=name))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ref", default="origin/editorial-intake")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--verify-tree", action="store_true")
    args = ap.parse_args()
    if args.pending == args.verify_tree:
        ap.error("Select exactly one of --pending or --verify-tree")
    value = pending(args.ref) if args.pending else verify_tree(args.ref)
    print(json.dumps({"items": value}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
