#!/usr/bin/env python3
"""Safely refresh published Dzen URL evidence for site-first related links.

The upstream editorial catalog can temporarily lose archived titles. Never
replace previously verified evidence with an incomplete upstream record.
This script updates ONLY data/editorial_full_catalog_snapshot.json; it does
not publish articles, alter approved Markdown, or touch editorial-intake.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.site_related import verified

SOURCE = "AfterDark1000/dzen-telegram-crosspost/editorial_full_catalog.json"
SOURCE_URL = "https://raw.githubusercontent.com/" + SOURCE.replace("/editorial_full_catalog.json", "/main/editorial_full_catalog.json")
COMMITS_URL = ("https://api.github.com/repos/AfterDark1000/dzen-telegram-crosspost/"
               "commits?path=editorial_full_catalog.json&per_page=1")
TARGET = ROOT / "data" / "editorial_full_catalog_snapshot.json"
FIELDS = ("dzen_id", "title", "dzen_url", "url_evidence", "title_evidence",
          "source", "excerpt", "published_at_utc",
          "previous_workflow_title", "published_date", "published_date_evidence")


def blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def merge_snapshot(old, upstream, *, source_blob_sha, source_commit, snapshot_date):
    if old.get("schema_version") != 1 or not isinstance(old.get("entries"), list):
        raise ValueError("Invalid existing snapshot")
    if upstream.get("schema_version") != 1 or not isinstance(upstream.get("entries"), list):
        raise ValueError("Invalid upstream editorial catalog")
    old_rows = old["entries"]
    if not old_rows or not all(verified(item) for item in old_rows):
        raise ValueError("Existing snapshot has unverified records; manual review required")
    saved = {item["dzen_id"]: item for item in old_rows}
    if len(saved) != len(old_rows):
        raise ValueError("Duplicate ID in existing snapshot")

    upstream_ids = set()
    trusted_count = 0
    for item in upstream["entries"]:
        ident = item.get("dzen_id") if isinstance(item, dict) else None
        if ident in upstream_ids:
            raise ValueError("Duplicate ID in upstream catalog: " + str(ident))
        upstream_ids.add(ident)
        if not verified(item):
            # Unknown/unproven URLs never enter the site catalog.
            # A previously verified version of this same ID remains intact.
            continue
        trusted_count += 1
        if ident in saved:
            if saved[ident]["dzen_url"] != item["dzen_url"]:
                raise ValueError("Conflicting verified Dzen URL: " + ident)
            # Keep stronger historical evidence (original publication date,
            # verified-page provenance and titles) intact. Newer upstream
            # snapshots may omit some of those irreplaceable details.
            continue
        saved[ident] = {field: item[field] for field in FIELDS if field in item}
    if trusted_count < 100:
        raise ValueError("Suspicious collapse of verified upstream Dzen links")

    result = {
        "schema_version": 1,
        "source": SOURCE,
        "source_commit": source_commit,
        "source_blob_sha": source_blob_sha,
        "snapshot_date": snapshot_date,
        "purpose": ("Read-only verified Dzen links. Retain previously proven links "
                    "if upstream later loses titles; never promote derived or unverified URLs."),
        "entries": sorted(saved.values(), key=lambda item: item["dzen_id"], reverse=True),
    }
    if len(result["entries"]) < len(old_rows) or not all(verified(item) for item in result["entries"]):
        raise ValueError("Unsafe catalog merge")
    return result


def retrieve(url):
    headers = {"User-Agent": "HPII-verified-Dzen-catalog-sync",
               "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN", "")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = "Bearer " + token
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Update snapshot if needed")
    args = parser.parse_args()
    raw = retrieve(SOURCE_URL)
    upstream = json.loads(raw.decode("utf-8"))
    old = json.loads(TARGET.read_text(encoding="utf-8"))
    sha = blob_sha(raw)

    # Avoid a second network call if this exact upstream blob is already imported.
    if old.get("source_blob_sha") == sha and old.get("source_commit"):
        commit = old["source_commit"]
    else:
        changes = json.loads(retrieve(COMMITS_URL).decode("utf-8"))
        if not isinstance(changes, list) or not changes or not isinstance(changes[0].get("sha"), str):
            raise ValueError("Cannot confirm upstream catalog revision")
        commit = changes[0]["sha"]
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    if old.get("source_blob_sha") == sha and old.get("snapshot_date"):
        today = old["snapshot_date"]
    merged = merge_snapshot(old, upstream, source_blob_sha=sha,
                            source_commit=commit, snapshot_date=today)
    output = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
    original = TARGET.read_text(encoding="utf-8")
    print("VERIFIED_DZEN_CATALOG:", len(old["entries"]), "->", len(merged["entries"]),
          "source_blob=", sha, "changed=", output != original, flush=True)
    if output != original and args.write:
        TARGET.write_text(output, encoding="utf-8")
    elif output != original:
        raise SystemExit("Catalog snapshot needs refresh; rerun with --write")


if __name__ == "__main__":
    main()
