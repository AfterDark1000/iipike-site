#!/usr/bin/env python3
"""Register published Dzen counterparts of site-first HPII articles.

Fetch catalog separately; this script never needs Dzen credentials. Read-only
unless --apply is given. Only authoritative *public feed* entries with exact
approved headline and publication after the site release are eligible.
It alters news.json metadata and rendered HTML crosslinks, never the editor's
approved Markdown, published date, or Dzen/social publishing queues.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.publish_approved_article import approved_article, render_article
from scripts.site_related import catalog_entries, verified

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def clean_title(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def utc(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Missing Dzen/site publication timestamp")
    t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("Publication timestamp lacks timezone")
    return t.astimezone(dt.timezone.utc)


def site_first(root, record):
    """Identify approved site-first output, not historical Dzen migrations."""
    slug = record.get("id")
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        return False
    if (record.get("dzen_id") or record.get("dzen_url") or
            record.get("site_first_dzen_id") or record.get("site_first_dzen_url")):
        return False
    approved_path = root / "content" / "approved" / (slug + ".json")
    inbox_path = root / "editorial_inbox" / "stories" / (slug + ".json")
    if not approved_path.is_file() or not inbox_path.is_file():
        return False
    data = json.loads(approved_path.read_text(encoding="utf-8"))
    inbound = json.loads(inbox_path.read_text(encoding="utf-8"))
    # Earliest site-first pilot records used validated paragraph blocks;
    # current releases keep the verbatim approved Markdown.
    source_matches = (
        isinstance(data.get("article_markdown"), str)
        and data["article_markdown"] == inbound.get("article_markdown")
    ) or (
        "article_markdown" not in data
        and isinstance(data.get("paragraphs"), list)
        and data["paragraphs"] == inbound.get("paragraphs")
    )
    return (data.get("status") == "approved"
            and source_matches
            and inbound.get("status") == "editor_approved"
            and inbound.get("approved_by") == "human_editor"
            and data.get("title") == record.get("title") == inbound.get("title")
            and data.get("published_at_utc") == record.get("published_at_utc"))


def matches(root, current, catalog):
    """Return only unambiguous verified site-first -> Dzen mappings."""
    if catalog.get("schema_version") != 1 or not isinstance(catalog.get("entries"), list):
        raise ValueError("Invalid published full Dzen catalog")
    trusted = {}
    for entry in catalog["entries"]:
        if not verified(entry) or not entry.get("title") or not entry.get("published_at_utc"):
            continue
        title = clean_title(entry["title"])
        trusted.setdefault(title, []).append(entry)
    # Historical migrations and site-first counterparts use distinct fields.
    claimed_ids = {r["dzen_id"]: r["id"] for r in current if r.get("dzen_id")}
    for r in current:
        if r.get("site_first_dzen_id"):
            ident = r["site_first_dzen_id"]
            if ident in claimed_ids and claimed_ids[ident] != r["id"]:
                raise ValueError("Dzen ID assigned to multiple article types")
            claimed_ids[ident] = r["id"]
    matched = {}
    for record in current:
        if not site_first(root, record):
            continue
        published = utc(record["published_at_utc"])
        options = []
        for entry in trusted.get(clean_title(record["title"]), []):
            try:
                when = utc(entry["published_at_utc"])
            except (ValueError, TypeError):
                continue
            # Site-first means site publication precedes the Dzen original.
            # Ten minutes tolerance for small feed clock discrepancies only.
            if when >= published - dt.timedelta(minutes=10):
                options.append(entry)
        if len(options) > 1:
            print("AMBIGUOUS_DZEN_TITLE: " + record["id"] + " (no change)")
            continue
        if not options:
            continue
        entry = options[0]
        dzen_id = entry["dzen_id"]
        if dzen_id in claimed_ids and claimed_ids[dzen_id] != record["id"]:
            raise ValueError("Dzen ID is already assigned to another article")
        claimed_ids[dzen_id] = record["id"]
        matched[record["id"]] = entry
    return matched


def plan(root, catalog):
    records_path = root / "news.json"
    original = json.loads(records_path.read_text(encoding="utf-8"))
    if not isinstance(original, list):
        raise ValueError("Site article index is invalid")
    linked = matches(root, original, catalog)
    if not linked:
        return {}, {}
    updated = json.loads(json.dumps(original, ensure_ascii=False))
    changed_urls = set()
    for record in updated:
        entry = linked.get(record["id"])
        if entry:
            # These are counterpart metadata, NOT historical migration origin.
            # Historical archive checks require dzen_id/dzen_url only on
            # articles originally published in Dzen.
            record["site_first_dzen_id"] = entry["dzen_id"]
            record["site_first_dzen_url"] = entry["dzen_url"]
            changed_urls.add(entry["dzen_url"])
    outputs = {
        records_path: json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    }
    historical_catalog = None
    # Regenerate only approved pages actually containing one of the
    # newly registered Dzen URLs; never touch hand-authored pilot pages.
    for record in updated:
        url = record.get("url", "")
        if not re.fullmatch(r"articles/[a-z0-9]+(?:-[a-z0-9]+)*/", url):
            continue
        page = root / url / "index.html"
        if not page.is_file():
            continue
        existing_html = page.read_text(encoding="utf-8")
        if not any(dzen_url in existing_html for dzen_url in changed_urls):
            continue
        source = root / "content" / "approved" / (record["id"] + ".json")
        if not source.is_file():
            continue
        article = approved_article(root, record["id"])
        if article.get("related_dzen_ids"):
            if historical_catalog is None:
                historical_catalog = catalog_entries(root)
            related = historical_catalog
        else:
            related = {}
        rendered = render_article(article, updated, related)
        if rendered != existing_html:
            outputs[page] = rendered
    return linked, outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path,
                        help="Fresh editorial_full_catalog.json from the public crosspost repository")
    parser.add_argument("--apply", action="store_true", help="Write validated site-only changes")
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    matched, outputs = plan(ROOT, catalog)
    if not matched:
        print("NO_NEW_VERIFIED_DZEN_LINKS: site unchanged")
        return
    for slug, entry in sorted(matched.items()):
        print("LINK_FOUND: " + slug + " <- " + entry["dzen_url"])
    if not args.apply:
        print("DRY_RUN: would update " + str(len(outputs)) + " local files; nothing written")
        return
    for path, body in outputs.items():
        path.write_text(body, encoding="utf-8")
    print("LINK_SYNC_OK: " + str(len(matched)) + " matches; "
          + str(len(outputs)) + " site files updated (no publication in Dzen)")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, TypeError, OSError, KeyError, json.JSONDecodeError) as exc:
        sys.exit("Site-first Dzen link sync rejected: " + str(exc))
