#!/usr/bin/env python3
"""Show candidate historically related articles; read-only, never auto-publish."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.site_related import catalog_entries, suggest



def main():
    p = argparse.ArgumentParser()
    p.add_argument("slug")
    a = p.parse_args()
    path = ROOT / "content" / "approved" / (a.slug + ".json")
    data = json.loads(path.read_text(encoding="utf-8"))
    for common, title, ident in suggest(data, catalog_entries(ROOT)):
        print(f"{common} matches  {ident}  {title}")
    print("Candidates require editorial review; only explicitly selected links are rendered.")


if __name__ == "__main__":
    main()
