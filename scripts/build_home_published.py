#!/usr/bin/env python3
"""Maintain indexable homepage article links from the first-party news.json."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.site_home import update_home


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify without writing")
    args = parser.parse_args()
    html = ROOT / "index.html"
    records = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
    before = html.read_text(encoding="utf-8")
    after = update_home(before, records, root=ROOT)
    if args.check:
        if before != after:
            parser.exit(1, "Homepage site articles need regeneration: python3 scripts/build_home_published.py\n")
        print("Homepage article list is current")
    else:
        html.write_text(after, encoding="utf-8")
        print("Homepage first-party articles updated")


if __name__ == "__main__":
    main()
