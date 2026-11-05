#!/usr/bin/env python3
"""One-time, fail-closed cleanup of the 218 verified historical Dzen pages.

Only remove duplicated visible summary and Dzen-provenance-only UI. Keep the
original lead/body, original date, cover, canonical, metadata/JSON-LD, source
record and any REAL external primary source exactly as they were.
This tool never creates a publication and does not update editorial content.
"""
import argparse
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def replace_optional_once(source, old, new, name):
    occurrences = source.count(old)
    if occurrences > 1:
        raise ValueError("Repeated " + name)
    return (source.replace(old, new, 1) if occurrences else source), bool(occurrences)


def cleanup_html(record, approved, markup):
    if not record.get("dzen_id"):
        raise ValueError("Not an original Dzen migration")
    for field in ("title", "summary", "published", "dzen_id", "dzen_url", "source_url"):
        if record.get(field) != approved.get(field):
            raise ValueError("Unmatched approved provenance: " + record["id"] + "/" + field)
    original = markup
    summary = '<p class="summary">' + html.escape(record["summary"], quote=True) + '</p>'
    markup, removed = replace_optional_once(markup, summary, "", "visible summary")
    head = markup.split("<figure class=\"cover\">", 1)[0]
    if not removed and '<p class="summary">' in head:
        raise ValueError("Unexpected historical header summary: " + record["id"])

    dzen_url = html.escape(record["dzen_url"], quote=True)
    dzen_link = ('<p class="date"><a href="' + dzen_url
                 + '" target="_blank" rel="noopener noreferrer">Версия в Дзене ↗</a></p>')
    markup, removed = replace_optional_once(markup, dzen_link, "", "version-in-Dzen link")
    if not removed and "Версия в Дзене" in markup:
        raise ValueError("Unexpected Dzen outbound header link: " + record["id"])

    if approved["source_url"] == approved["dzen_url"]:
        source_title = html.escape(approved["source_title"], quote=True)
        old_sidebar = (
            '<section class="article-body"><aside class="sources"><h3>Архивная публикация</h3>\n'
            '<a href="' + dzen_url + '" target="_blank" rel="noopener noreferrer">'
            + source_title + ' ↗</a>\n</aside><article class="article-text">'
        )
        new_body = '<section class="article-body archive-body"><article class="article-text">'
        markup, removed = replace_optional_once(markup, old_sidebar, new_body,
                                                "Dzen provenance-only sidebar")
        if not removed and markup.count(new_body) != 1:
            raise ValueError("Cannot locate Dzen provenance sidebar: " + record["id"])
    else:
        # The genuine primary research/company source remains visible.
        external = 'href="' + html.escape(approved["source_url"], quote=True) + '"'
        if markup.count(external) < 1 or '<h3>Первоисточник</h3>' not in markup:
            raise ValueError("Missing genuine external primary source: " + record["id"])

    # A renderer update is not permitted to truncate, reshape or rephrase the article.
    marker = '<article class="article-text">'
    if marker not in markup or original.split(marker, 1)[1] != markup.split(marker, 1)[1]:
        raise ValueError("Article text changed unexpectedly: " + record["id"])
    for signature in ('<link rel="canonical" ', '"datePublished": ', '<figure class="cover">'):
        if original.count(signature) != markup.count(signature):
            raise ValueError("Original page provenance altered: " + record["id"])
    if record["dzen_url"] not in markup:
        raise ValueError("Verified Dzen provenance lost from structured data")
    return markup


def plan(root=ROOT):
    rows = json.loads((root / "news.json").read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Invalid news.json")
    migrated = [row for row in rows if row.get("dzen_id")]
    if len(migrated) < 200:
        raise ValueError("Historical archive unexpectedly small: " + str(len(migrated)))
    updates = {}
    for row in migrated:
        slug = row["id"]
        source = root / "content" / "approved" / (slug + ".json")
        target = root / row["url"] / "index.html"
        if not source.is_file() or not target.is_file():
            raise ValueError("Missing approved source or published HTML: " + slug)
        approved = json.loads(source.read_text(encoding="utf-8"))
        existing = target.read_text(encoding="utf-8")
        changed = cleanup_html(row, approved, existing)
        if changed != existing:
            updates[target] = changed
    return len(migrated), updates


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--apply", action="store_true", help="Write validated article HTML")
    args.add_argument("--assert-clean", action="store_true", help="Fail if any historical page still needs changes")
    opt = args.parse_args()
    count, updates = plan()
    print("Historical pages checked:", count, "HTML pages to update:", len(updates))
    if opt.assert_clean and updates:
        raise ValueError(str(len(updates)) + " historical pages still require header cleanup")
    if opt.apply and updates:
        for path, content in updates.items():
            path.write_text(content, encoding="utf-8")
        print("CLEANUP_APPLIED:", len(updates), "pages; no source/date/cover changes")
    elif not opt.apply:
        print("READ_ONLY: no content changed")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as err:
        sys.exit("Historical header cleanup rejected: " + str(err))
