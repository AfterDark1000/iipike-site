#!/usr/bin/env python3
"""Generate or check safe static topic index and landing pages."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.site_topics import render_all_topics

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rows = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
    for path, content in render_all_topics(rows, ROOT).items():
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                parser.exit(1, "Topic page outdated: " + str(path) + "\n")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    print("Topic pages checked" if args.check else "Topic pages updated")

if __name__ == "__main__":
    main()
