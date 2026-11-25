#!/usr/bin/env python3
"""Refresh existing special-project presentation only. Never publish articles."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from scripts.site_dossier import load_ids, rows_for, archive, mark_article, update_home_dossier

def plan(root=ROOT):
    ids=load_ids(root)
    records=json.loads((root/"news.json").read_text(encoding="utf-8"))
    rows=rows_for(records,ids)
    for row in rows:
        if not (root/row["cover"]).is_file() or not (root/row["url"]/"index.html").is_file():
            raise ValueError("Missing published Dossier assets: "+row["id"])
    home=root/"index.html"
    outputs={home:update_home_dossier(home.read_text(encoding="utf-8"),records,root),
             root/"dossier/index.html":archive(records,ids)}
    for r in records:
        path=root/r["url"]/"index.html"
        original=path.read_text(encoding="utf-8")
        if r["id"] in ids or 'class="dossier-article-marker"' in original:
            outputs[path]=mark_article(original,r["id"],ids)
    return {p:content for p,content in outputs.items()
            if not p.is_file() or p.read_text(encoding="utf-8")!=content}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check",action="store_true")
    args=p.parse_args()
    outputs=plan()
    print("Dossier presentation changes:",len(outputs))
    if args.check:
        if outputs: raise SystemExit("Dossier presentation is outdated")
        return
    for path,content in outputs.items():
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(content,encoding="utf-8")

if __name__=="__main__":
    main()
