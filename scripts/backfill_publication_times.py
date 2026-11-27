#!/usr/bin/env python3
"""One-time safe label refresh for already published articles, home, archive, rubrics.

Never creates or approves an article; does not touch article prose, status or RSS.
"""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.site_rubrics import publication_label, render_all
from scripts.site_home import update_home
from scripts.publish_approved_article import render_catalog_pages

DATE = re.compile(r'(<p class="date">Опубликовано: )([^<]*)(</p>)')


def output_map(root):
    root = Path(root)
    rows = json.loads((root / "news.json").read_text(encoding="utf-8"))
    results = {
        **render_catalog_pages(rows, root),
        root / "index.html": update_home((root / "index.html").read_text(encoding="utf-8"),
                                       rows, root=root)
    }
    results.update(render_all(rows, root))
    revised, missing = 0, []
    for row in rows:
        if not row.get("published_at_utc") or row.get("publication_date_precision") == "day":
            continue
        path = root / row["url"] / "index.html"
        if not path.is_file():
            missing.append(row["id"])
            continue
        original = path.read_text(encoding="utf-8")
        if not DATE.search(original):
            missing.append(row["id"])
            continue
        new_text, n = DATE.subn(
            lambda match: match.group(1) + publication_label(row) + match.group(3),
            original, count=1
        )
        if n != 1:
            raise ValueError("Unsafe publication date replacement " + row["id"])
        if new_text != original:
            results[path] = new_text
            revised += 1
    return results, {"article_dates_updated": revised, "without_date_marker": missing}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    out, report = output_map(ROOT)
    changes = [(path, content) for path, content in out.items()
               if not path.exists() or path.read_text(encoding="utf-8") != content]
    if args.write:
        for path, content in changes:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    print(json.dumps({"changes": len(changes), "wrote": args.write, **report},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
