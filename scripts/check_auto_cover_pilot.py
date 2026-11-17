#!/usr/bin/env python3
"""Read-only validator for isolated autonomous cover candidates. Never publishes."""
import hashlib
import json
import re
import struct
from pathlib import Path

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
    if info["image_path"] != str(COVERS / (stem + ".png")):
        raise ValueError("Unsafe image path")
    png_path = Path(info["image_path"])
    png = png_path.read_bytes()
    if len(png) < 1024 or png[:8] != b"\x89PNG\r\n\x1a\n" or png[12:16] != b"IHDR":
        raise ValueError("Image has no real PNG header")
    width, height = struct.unpack(">II", png[16:24])
    if width < 640 or height < 360 or abs(width / height - 16/9) > 0.02:
        raise ValueError("Invalid PNG aspect ratio")
    if info["width"] != width or info["height"] != height:
        raise ValueError("Wrong recorded image dimensions")
    if git_blob_sha(png) != info["image_blob_sha"]:
        raise ValueError("PNG does not match recorded Git blob")
    draft = ROOT / "auto_drafts" / (article_id + ".json")
    decision = ROOT / "auto_decisions" / (article_id + "-r" + revision + ".json")
    draft_bytes, decision_bytes = draft.read_bytes(), decision.read_bytes()
    if git_blob_sha(draft_bytes) != info["source_draft_blob_sha"]:
        raise ValueError("Text draft changed")
    if git_blob_sha(decision_bytes) != info["source_decision_blob_sha"]:
        raise ValueError("Approval decision changed")
    body, approval = json.loads(draft_bytes), json.loads(decision_bytes)
    if (body["article_id"] != article_id or body["revision"] != int(revision)
            or body["updated_at"] != info["text_updated_at"]
            or approval["status"] != "text_approved_cover_pending"
            or approval["action"] != "approve_text"
            or approval["draft_blob_sha"] != info["source_draft_blob_sha"]):
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
