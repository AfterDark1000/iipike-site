#!/usr/bin/env python3
"""One-time controlled header-only backfill of published company/product chips.

Always preserve exact article content from the cover onward; never rewrite the
Dzen source, approved files, article body, publication metadata, or news.json.
"""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.site_entities import (
    inject_article_entity_nav, load_registry, render_article_entity_nav
)

COVER = '<figure class="cover">'
NAV_START = '<nav class="article-entity-links" aria-label="Компании и продукты статьи">'
NAV_PATTERN = re.compile(re.escape(NAV_START) + r'.*?</nav>', re.DOTALL)
CSS = '<link rel="stylesheet" href="../../assets/entities.css">'
BODY = '<article class="article-text">'


def update_header(html, slug, registry, original_registry):
    expected = render_article_entity_nav(slug, registry)
    if not expected:
        if NAV_START in html:
            raise ValueError("Old entity chips no longer in registry: " + slug)
        return html
    if html.count(COVER) != 1 or html.count(BODY) != 1:
        raise ValueError("Unexpected article/cover structure: " + slug)
    head, suffix = html.split(COVER, 1)
    if head.count('<div class="article-title">') != 1:
        raise ValueError("Unknown article header structure: " + slug)
    if NAV_START not in head:
        updated = inject_article_entity_nav(html, slug, registry)
    else:
        found = list(NAV_PATTERN.finditer(head))
        old_expected = render_article_entity_nav(slug, original_registry)
        if len(found) != 1 or head.count(NAV_START) != 1:
            raise ValueError("Multiple/unrecognized header entity navs: " + slug)
        if found[0].group(0) not in {old_expected, expected}:
            raise ValueError("Original company/product nav was modified: " + slug)
        if head.count(CSS) != 1:
            raise ValueError("Existing entity stylesheet is missing/duplicated: " + slug)
        updated = head[:found[0].start()] + expected + head[found[0].end():] + COVER + suffix
    if updated.split(COVER, 1)[1] != suffix:
        raise ValueError("Article text/cover/footer changed: " + slug)
    if updated.split(BODY, 1)[1] != html.split(BODY, 1)[1]:
        raise ValueError("Approved article text changed: " + slug)
    updated_head = updated.split(COVER, 1)[0]
    if updated_head.count(expected) != 1 or updated_head.count(CSS) != 1:
        raise ValueError("Entity nav not unique: " + slug)
    return updated


def plan(root=ROOT):
    root = Path(root)
    registry = load_registry(root)
    pilot = json.loads((root / "data" / "entity_pilot.json").read_text(encoding="utf-8"))
    records = json.loads((root / "news.json").read_text(encoding="utf-8"))
    known = {x["id"] for x in records}
    selected = {
        slug for kind in ("companies", "products") for entry in registry[kind]
        for slug in entry["article_ids"]
    }
    if len(known) != len(records) or not selected <= known:
        raise ValueError("Registry contains unknown/duplicate published IDs")
    outputs = {}
    for item in records:
        path = root / item["url"] / "index.html"
        if not path.is_file() or path.is_symlink():
            raise ValueError("Published article HTML missing/unsafe: " + str(path))
        before = path.read_text(encoding="utf-8")
        after = update_header(before, item["id"], registry, pilot)
        if after != before:
            if item["id"] not in selected:
                raise ValueError("Non-curated article changed: " + item["id"])
            outputs[path] = after
    return selected, outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Rewrite reviewed article headers only")
    parser.add_argument("--check", action="store_true", help="Fail if reviewed headers remain outdated")
    args = parser.parse_args()
    selected, outputs = plan()
    if args.check and outputs:
        raise SystemExit("Unapplied safe entity headers: " + str(len(outputs)))
    if args.apply:
        for path, content in outputs.items():
            path.write_text(content, encoding="utf-8")
    print("Entity backfill:", len(selected), "curated articles;",
          len(outputs), "headers updated" if args.apply else "headers to update")


if __name__ == "__main__":
    main()
