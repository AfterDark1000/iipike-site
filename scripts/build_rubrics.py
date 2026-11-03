#!/usr/bin/env python3
"""Build category pages from *published on-site* news.json entries only."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.site_rubrics import render_all



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    records = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
    results = render_all(records, ROOT)
    for path, rendered in results.items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != rendered:
                parser.exit(1, f"Rubric HTML outdated: {path}\n")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
    print("Rubric pages checked" if args.check else "Rubric pages updated")


if __name__ == "__main__":
    main()
