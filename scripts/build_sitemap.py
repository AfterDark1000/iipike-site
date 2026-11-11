#!/usr/bin/env python3
"""Build a sitemap of reviewed, publicly published HPII site pages only.

Never include editorial previews, internal registry pages or Dzen-only URLs.
The editorially controlled news.json is the allowlist of live site articles.
"""
import argparse
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.site_rubrics import populated, RUBRICS
from scripts.site_topics import active_topics
from scripts.site_entities import entity_urls, load_registry
BASE = "https://iipike.ru"
SITEMAP = ROOT / "sitemap.xml"
SLUG_PATH = re.compile(r"articles/[a-z0-9]+(?:-[a-z0-9]+)*/")


def get_urls():
    records = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("news.json must be a list of published articles")
    urls = [BASE + "/", BASE + "/articles/"]
    for key in populated(records):
        if not (ROOT / "rubrics" / key / "index.html").is_file():
            raise ValueError(f"Rubric HTML missing: {key}")
        urls.append(BASE + "/rubrics/" + key + "/")
    # Before the one-time migration the topic directory does not yet exist.
    # Never claim a discoverable URL until its reviewed static HTML is built.
    topics_directory = ROOT / "topics" / "index.html"
    if topics_directory.is_file():
        if f'rel="canonical" href="{BASE}/topics/"' not in topics_directory.read_text(encoding="utf-8"):
            raise ValueError("Topics index canonical missing")
        urls.append(BASE + "/topics/")
        for key in active_topics(records):
            page = ROOT / "topics" / key / "index.html"
            if not page.is_file():
                raise ValueError("Topic page missing: " + key)
            contents = page.read_text(encoding="utf-8")
            if f'rel="canonical" href="{BASE}/topics/{key}/"' not in contents:
                raise ValueError("Invalid topic canonical for " + key)
            if re.search(r"<meta[^>]*name=.robots.[^>]*noindex", contents, re.IGNORECASE):
                raise ValueError("Populated topic page is noindex: " + key)
            urls.append(BASE + "/topics/" + key + "/")
    # Public company/product archives contain only curated, published stories.
    # Require their canonical pages to exist before exposing them to search.
    for url in entity_urls(load_registry(ROOT)):
        path = ROOT / url.removeprefix(BASE + "/") / "index.html"
        if not path.is_file():
            raise ValueError("Entity page missing: " + str(path))
        contents = path.read_text(encoding="utf-8")
        if f'rel="canonical" href="{url}"' not in contents:
            raise ValueError("Invalid entity canonical for " + url)
        if re.search(r"<meta[^>]*name=.robots.[^>]*noindex", contents, re.IGNORECASE):
            raise ValueError("Public entity page is noindex: " + url)
        urls.append(url)
    seen = set()
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("Invalid article metadata in news.json")
        rel = item.get("url")
        if not isinstance(rel, str) or not SLUG_PATH.fullmatch(rel):
            raise ValueError(f"Unsafe or non-article publication path: {rel!r}")
        if rel in seen:
            raise ValueError(f"Duplicate article URL: {rel}")
        seen.add(rel)
        page = ROOT / rel / "index.html"
        if not page.is_file():
            raise ValueError(f"Published article HTML is missing: {page}")
        html = page.read_text(encoding="utf-8")
        url = BASE + "/" + rel
        if f'rel="canonical" href="{url}"' not in html:
            raise ValueError(f"Missing/mismatched canonical for {rel}")
        if re.search(r'<meta\s+name=["\']robots["\'][^>]*noindex', html, re.IGNORECASE):
            raise ValueError(f"Published page is marked noindex: {rel}")
        urls.append(url)
    return urls


def render():
    urls = get_urls()
    records = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
    updates = {BASE + "/" + item["url"]: item["modified_at_utc"] for item in records
               if item.get("modified_at_utc")}
    def row(url):
        lastmod = f"<lastmod>{escape(updates[url])}</lastmod>" if url in updates else ""
        return f"  <url><loc>{escape(url)}</loc>{lastmod}</url>"
    rows = "\n".join(row(url) for url in urls)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + rows + '\n</urlset>\n'
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if sitemap is stale; do not write")
    args = parser.parse_args()
    content = render()
    if args.check:
        if not SITEMAP.is_file() or SITEMAP.read_text(encoding="utf-8") != content:
            parser.exit(1, "sitemap.xml is outdated: run python3 scripts/build_sitemap.py\n")
        print("sitemap.xml matches reviewed HTML publications")
    else:
        SITEMAP.write_text(content, encoding="utf-8")
        print("Updated", SITEMAP)


if __name__ == "__main__":
    main()
