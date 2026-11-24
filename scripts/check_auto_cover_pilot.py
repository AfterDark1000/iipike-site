#!/usr/bin/env python3
"""Read-only validator for isolated autonomous cover candidates. Never publishes."""
import hashlib
import json
import re
import subprocess
from pathlib import Path
from PIL import Image, UnidentifiedImageError

ROOT = Path("editorial_inbox")
COVERS = ROOT / "auto_covers"
VALID_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
VALID_NAME = re.compile(r"([a-z0-9]+(?:-[a-z0-9]+)*)-r([1-9][0-9]*)-v([1-9][0-9]*)")


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def validate(meta_path: Path) -> None:
    info = json.loads(meta_path.read_text(encoding="utf-8"))
    stem = meta_path.stem
    match = VALID_NAME.fullmatch(stem)
    if not match:
        raise ValueError("Invalid cover candidate name")
    article_id, revision, version = match.groups()
    required = {
        "schema_version", "article_id", "text_revision", "text_updated_at",
        "source_draft_blob_sha", "source_decision_blob_sha", "status", "image_path",
        "image_blob_sha", "width", "height", "concept", "headline", "artist_notes",
        "created_at"
    }
    if set(info) != required:
        raise ValueError("Cover metadata fields mismatch")
    if info["schema_version"] != 1 or info["article_id"] != article_id:
        raise ValueError("Wrong cover ID")
    if info["text_revision"] != int(revision) or info["status"] != "ready_for_cover_review":
        raise ValueError("Wrong cover status or revision")
    if info["image_path"] != str(COVERS / (stem + ".webp")):
        raise ValueError("Unsafe image path")
    image_path = Path(info["image_path"])
    image_bytes = image_path.read_bytes()
    if (len(image_bytes) < 1024 or len(image_bytes) > 800_000 or
            image_bytes[:4] != b"RIFF" or image_bytes[8:12] != b"WEBP"):
        raise ValueError("Not a compact genuine WebP container")
    try:
        with Image.open(image_path) as image:
            if image.format != "WEBP":
                raise ValueError("Not actual WebP")
            image.load()
            width, height = image.size
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("WebP pixels cannot be decoded") from exc
    if width < 640 or height < 360 or abs(width / height - 16/9) > 0.02:
        raise ValueError("Invalid WebP aspect ratio")
    if info["width"] != width or info["height"] != height:
        raise ValueError("Wrong recorded image dimensions")
    if git_blob_sha(image_bytes) != info["image_blob_sha"]:
        raise ValueError("WebP does not match recorded Git blob")
    draft = ROOT / "auto_drafts" / (article_id + ".json")
    decision = ROOT / "auto_decisions" / (article_id + "-r" + revision + ".json")
    draft_sha = info["source_draft_blob_sha"]
    if not isinstance(draft_sha, str) or not re.fullmatch(r"[a-f0-9]{40}", draft_sha):
        raise ValueError("Invalid source draft Git SHA")
    draft_bytes = draft.read_bytes() if draft.exists() else b""
    # Historical cover candidates survive later text revisions; audit the exact
    # historical source blob, never transfer an old candidate to the current rN.
    if git_blob_sha(draft_bytes) != draft_sha:
        draft_bytes = subprocess.check_output(["git", "cat-file", "blob", draft_sha])
    if git_blob_sha(draft_bytes) != draft_sha:
        raise ValueError("Text draft SHA mismatch")
    body = json.loads(draft_bytes)
    if (body["article_id"] != article_id or body["revision"] != int(revision)
            or body["updated_at"] != info["text_updated_at"]
            or body["status"] != "ready_for_review"):
        raise ValueError("No matching ready text revision")
    decision_sha = info["source_decision_blob_sha"]
    if decision_sha is not None:
        decision_bytes = decision.read_bytes()
        if git_blob_sha(decision_bytes) != decision_sha:
            raise ValueError("Approval decision changed")
        approval = json.loads(decision_bytes)
        if (approval["status"] != "text_approved_cover_pending"
                or approval["action"] != "approve_text"
                or approval["draft_blob_sha"] != draft_sha):
            raise ValueError("No matching text approval")
    if any(not isinstance(info[k], str) or not info[k].strip() for k in ("concept", "headline", "created_at")):
        raise ValueError("Empty cover content")


if __name__ == "__main__":
    if not COVERS.exists():
        print("No cover candidates yet")
    else:
        items = sorted(COVERS.glob("*.json"))
        for path in items:
            validate(path)
        print(f"Validated {len(items)} auto-cover candidate(s); NO PUBLICATION")
