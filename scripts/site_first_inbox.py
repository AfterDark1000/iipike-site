#!/usr/bin/env python3
"""Stage a ChatGPT-editor-approved story + its original artwork for iipike.ru.

This is NOT the experimental Gemini draft pipeline, and NOT Dzen crossposting.
No network requests, GitHub pushes, social dispatch or background publication.
The approved story arrives independently of the image from any ChatGPT chat.
Only an explicit --stage [--publish] on a release branch changes site files.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.publish_approved_article import approved_article, publish
from scripts.site_rubrics import RUBRICS

EDITORIAL_TZ = ZoneInfo("Asia/Yekaterinburg")
STORY_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
COVER_EXTENSIONS = {"webp": "WEBP", "png": "PNG", "jpg": "JPEG", "jpeg": "JPEG"}
KINDS = {"lead", "p", "h2"}
ALLOWED_FIELDS = {
    "schema_version", "id", "status", "approved_by", "approved_at", "title",
    "dzen_title", "summary", "rubric", "section", "source_url", "source_title",
    "event_date", "related_dzen_ids", "paragraphs", "threads_queue_id", "x_queue_id",
}
MAX_IMAGE_BYTES = 16 * 1024 * 1024


def required_text(record, key, limit):
    val = record.get(key)
    if not isinstance(val, str) or not val.strip() or len(val) > limit:
        raise ValueError(f"Missing/invalid {key}")
    return val.strip()


def validate_story(root, story_id, *, today=None):
    if not isinstance(story_id, str) or len(story_id) > 72 or not STORY_ID.fullmatch(story_id):
        raise ValueError("Invalid stable editorial ID")
    path = root / "editorial_inbox" / "stories" / (story_id + ".json")
    if not path.is_file() or path.is_symlink():
        raise ValueError("Approved ChatGPT editorial story is missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) - ALLOWED_FIELDS:
        raise ValueError("Invalid or forbidden inbound story fields")
    if data.get("schema_version") != 1 or data.get("id") != story_id:
        raise ValueError("Wrong inbox schema or story ID")
    if data.get("status") != "editor_approved":
        raise ValueError("Text has not received explicit 'берём' approval")
    if data.get("approved_by") != "human_editor":
        raise ValueError("Approval must originate from the human editor")
    approval = dt.date.fromisoformat(required_text(data, "approved_at", 10))
    current = today or dt.datetime.now(EDITORIAL_TZ).date()
    if approval > current:
        raise ValueError("Approval date cannot be in the future")
    title = required_text(data, "title", 500)
    if title != required_text(data, "dzen_title", 500):
        raise ValueError("Dzen and site title must match for existing crosspost queue")
    if required_text(data, "rubric", 80) not in RUBRICS:
        raise ValueError("Unknown HPII rubric")
    for name, limit in (("summary", 1500), ("section", 120), ("source_title", 500)):
        required_text(data, name, limit)
    original = required_text(data, "source_url", 2000)
    u = urlsplit(original)
    if (u.scheme != "https" or not u.hostname or u.username or u.password or
            u.port not in (None, 443) or any(c.isspace() for c in original)):
        raise ValueError("Original source must be a safe HTTPS URL")
    if "event_date" in data:
        dt.date.fromisoformat(required_text(data, "event_date", 10))
    related = data.get("related_dzen_ids", [])
    if not isinstance(related, list) or len(related) > 4 or len(set(map(str, related))) != len(related):
        raise ValueError("Related article IDs must be a distinct list of at most four")
    if any(not isinstance(x, str) or not re.fullmatch(r"[0-9a-f]{24}", x) for x in related):
        raise ValueError("Related Dzen IDs must be canonical 24-hex values")
    for optional in ("threads_queue_id", "x_queue_id"):
        if optional in data and (not isinstance(data[optional], str) or
                                 not re.fullmatch(r"[a-zA-Z0-9_-]{8,72}", data[optional])):
            raise ValueError("Invalid stable social queue identifier: " + optional)
    blocks = data.get("paragraphs")
    if not isinstance(blocks, list) or not 2 <= len(blocks) <= 80:
        raise ValueError("Full approved Dzen article needs at least two text blocks")
    for index, block in enumerate(blocks):
        if (not isinstance(block, dict) or set(block) != {"type", "text"}
                or block["type"] not in KINDS):
            raise ValueError("Unsupported article paragraph structure")
        if index == 0 and block["type"] != "lead":
            raise ValueError("First paragraph must be the lead")
        if not isinstance(block["text"], str) or not block["text"].strip() or len(block["text"]) > 12000:
            raise ValueError("Article contains an empty or oversized paragraph")
    if len(" ".join(b["text"] for b in blocks)) < 400:
        raise ValueError("Cannot publish incomplete article text")
    entries = json.loads((root / "news.json").read_text(encoding="utf-8"))
    if (any(x.get("id") == story_id for x in entries) or
            (root / "articles" / story_id / "index.html").exists()):
        raise ValueError("Story already published on the site")
    if any(x.get("title", "").casefold() == title.casefold() or
           x.get("source_url") == original for x in entries):
        raise ValueError("Potential duplicate title or primary source on the site")
    return data


def cover_info(root, story_id):
    base = root / "editorial_inbox" / "covers"
    candidates = [base / (story_id + "." + suffix) for suffix in COVER_EXTENSIONS]
    matched = [p for p in candidates if p.is_file()]
    if not matched:
        return None
    if len(matched) != 1 or matched[0].is_symlink():
        raise ValueError("Ambiguous or unsafe cover file for this exact story ID")
    path = matched[0]
    if not 15_000 <= path.stat().st_size <= MAX_IMAGE_BYTES:
        raise ValueError("Cover image too small or too large")
    try:
        with Image.open(path) as image:
            width, height = image.size
            actual_format = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("Cover image cannot be decoded") from exc
    if actual_format != COVER_EXTENSIONS[path.suffix.lstrip(".")]:
        raise ValueError("Cover file extension does not match actual image data")
    if width < 780 or height < 430 or width * height > 40_000_000:
        raise ValueError("Cover does not have sufficient safe dimensions")
    if not 1.70 < width / height < 1.84:
        raise ValueError("Cover is not a proper 16:9 landscape (use a separate 4:5 version for IG)")
    return path, width, height


def stage(root, story_id, *, apply=False, now=None):
    """Validate independently delivered text+art, optionally create approved files.

    The publish timestamp is first assigned here, NOT at 'берём' time.
    Call only immediately before requesting a site release. The site becomes
    public only after site release branch is merged and Pages deploy succeeds.
    """
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Release timestamp must carry a timezone")
    current = current.astimezone(dt.timezone.utc)
    data = validate_story(root, story_id, today=current.astimezone(EDITORIAL_TZ).date())
    art = cover_info(root, story_id)
    if art is None:
        print(f"AWAITING_COVER: {story_id} (article stored; cannot release yet)")
        return None
    cover, width, height = art
    dest_asset = root / "assets" / "editorial" / cover.name
    dest_json = root / "content" / "approved" / (story_id + ".json")
    if dest_asset.exists() or dest_json.exists():
        raise ValueError("Already staged: cannot overwrite a live or approved article")
    timestamp = current.strftime("%Y-%m-%dT%H:%M:%SZ")
    date = current.astimezone(EDITORIAL_TZ).date().isoformat()
    approved = {
        "slug": story_id, "status": "approved",
        "approved_by": "Редактор ХПИИ — подтверждено человеком",
        "approved_at": data["approved_at"],
        "title": data["title"], "summary": data["summary"],
        "rubric": data["rubric"], "section": data["section"],
        "source_url": data["source_url"], "source_title": data["source_title"],
        "published": date, "published_at_utc": timestamp,
        "cover": dest_asset.relative_to(root).as_posix(),
        "paragraphs": data["paragraphs"],
        "related_dzen_ids": data.get("related_dzen_ids", []),
    }
    if "event_date" in data:
        approved["event_date"] = data["event_date"]
    if not apply:
        print(f"READY_FOR_SITE_RELEASE: {story_id}, image={width}x{height}; no files changed")
        return approved
    dest_json.parent.mkdir(parents=True, exist_ok=True)
    dest_asset.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(cover, dest_asset)
        dest_json.write_text(json.dumps(approved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Reuse the production publisher's entire provenance/date/text contract.
        approved_article(root, story_id)
    except Exception:
        dest_json.unlink(missing_ok=True)
        dest_asset.unlink(missing_ok=True)
        raise
    print(f"STAGED: {story_id} at {timestamp}; article not yet public")
    return approved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("story_id", help="Stable story ID in editorial_inbox/stories/")
    parser.add_argument("--stage", action="store_true", help="Explicitly create approved JSON and local cover")
    parser.add_argument("--publish", action="store_true", help="Also compile HTML and indexes in current branch")
    args = parser.parse_args()
    if args.publish and not args.stage:
        parser.exit(2, "--publish requires explicit --stage\n")
    try:
        approved = stage(ROOT, args.story_id, apply=args.stage)
        if approved is not None and args.publish:
            publish(ROOT, args.story_id, apply=False)
            publish(ROOT, args.story_id, apply=True)
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Site-first release rejected: {exc}\n")


if __name__ == "__main__":
    main()
