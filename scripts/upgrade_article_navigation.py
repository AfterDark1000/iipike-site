#!/usr/bin/env python3
"""One-time site navigation upgrade: clean duplicate category text and add topics.

Safe for old and new articles. It does not change approved editorial sources,
article text, original Dzen dates, covers, canonical addresses or publication
queues. The topics are persisted once, not silently reassigned on each build.
"""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.publish_approved_article import render_catalog, render_sitemap
from scripts.site_topics import (
    validate_topics, infer_topics, render_topic_links, render_all_topics
)

KICKER = re.compile(
    r'(<p class="kicker">)(<a href="../../rubrics/[a-z-]+/">[^<]+</a>)(?: / [^<]*)?(</p>)'
)
DATE_WITH_COVER = re.compile(
    r'(<p class="date">Опубликовано: [^<]+</p>)(</div>\n<figure class="cover">)'
)


def clean_article_html(page, topics, slug):
    updated, count = KICKER.subn(lambda m: m.group(1)+m.group(2)+m.group(3),
                                 page, count=1)
    if count != 1:
        raise ValueError("Article page has an unexpected rubric header: " + slug)
    rendered = render_topic_links(topics)
    # Always replace a previously generated topic list exactly where a date
    # ends, for idempotence and safe future rebuilds.
    pattern = re.compile(
        r'(<p class="date">Опубликовано: [^<]+</p>)'
        r'(<nav class="topic-links" aria-label="Темы статьи">.*?</nav>)?'
        r'(</div>\n<figure class="cover">)',
        re.DOTALL,
    )
    updated, count = pattern.subn(
        lambda m: m.group(1) + rendered + m.group(3), updated, count=1
    )
    if count != 1:
        raise ValueError("Missing date/cover boundary in historical article: " + slug)

    # The entire article body and everything after it remains byte-for-byte.
    marker = '<article class="article-text">'
    if marker not in page or marker not in updated:
        raise ValueError("Original article text not found: " + slug)
    if page.split(marker, 1)[1] != updated.split(marker, 1)[1]:
        raise ValueError("Editorial text or footer changed: " + slug)
    # Meta, original cover and canonical retain original source information.
    for marker in ('<script type="application/ld+json">', '<figure class="cover">',
                   '<link rel="canonical" '):
        if page.count(marker) != updated.count(marker):
            raise ValueError("Page provenance changed unexpectedly: " + slug)
    return updated


def plan(root=ROOT):
    index = root / "news.json"
    records = json.loads(index.read_text(encoding="utf-8"))
    if not isinstance(records, list) or len(records) < 200:
        raise ValueError("Historic article index is unexpectedly small")
    updated = json.loads(json.dumps(records, ensure_ascii=False))
    assignments = 0
    for row in updated:
        if "topics" in row:
            validate_topics(row["topics"])
        else:
            row["topics"] = infer_topics(row["title"], row["summary"])
            assignments += 1
    outputs = {}
    for row in updated:
        page = root / row["url"] / "index.html"
        if not page.is_file():
            raise ValueError("Published HTML missing: " + row["id"])
        before = page.read_text(encoding="utf-8")
        after = clean_article_html(before, row["topics"], row["id"])
        if after != before:
            outputs[page] = after
    new_index = json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    if index.read_text(encoding="utf-8") != new_index:
        outputs[index] = new_index
    # Don't change titles, HTML bodies or publication timestamps during this
    # navigation-only upgrade. Only the archive index and sitemap are rebuilt.
    generated = {
        root / "articles" / "index.html": render_catalog(updated),
        root / "sitemap.xml": render_sitemap(updated),
        **render_all_topics(updated, root),
    }
    for path, contents in generated.items():
        if not path.is_file() or path.read_text(encoding="utf-8") != contents:
            outputs[path] = contents
    return assignments, outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    count, outputs = plan()
    print("Topic metadata assignments:", count, "site files to update:", len(outputs))
    if args.check and outputs:
        raise ValueError("Article breadcrumbs/topic pages are not up to date")
    if args.apply:
        for path, content in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        print("APPLIED: navigation + topic metadata; original source text unchanged")
    else:
        print("READ_ONLY: no data modified")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as e:
        sys.exit("Topics upgrade rejected: " + str(e))
