#!/usr/bin/env python3
"""Inspect captured Dzen article image references. Read-only; no asset replacements."""
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
import concurrent.futures as cf

ROOT=Path(__file__).resolve().parents[1]
probes={e["slug"]:e for e in json.loads((ROOT/"research/batch5_probe_results.json").read_text())["results"]}
covers=json.loads((ROOT/"research/batch5_cover_report.json").read_text())["entries"]
data={e["dzen_id"]:e for e in json.loads((ROOT/"data/editorial_full_catalog_snapshot.json").read_text())["entries"]}
result=[]
for row in covers:
    if "get-zen-pub-og" not in row.get("url",""):continue
    probe=probes[row["slug"]]
    dom=probe.get("dom",{})
    entry=next((c for c in data.values() if c.get("title")==probe.get("expected_title")),None)
    url=probe.get("expected_url","")
    images=[x for x in dom.get("images",[]) if any(t in x.get("src","") for t in ("zen_doc","zen-pub","dzen","zen-media"))]
    result.append({"slug":row["slug"],"dzen_url":url,"dzen_id":entry["dzen_id"] if entry else None,
          "og_image":dom.get("og_image"),"images":images,"status":row["status"],
          "orig_cover":row["url"],"og_dims":[row.get("width"),row.get("height")]})
ROOT.joinpath("research/batch5_og_diagnostic.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
print("Affected by generated Dzen preview:",len(result))
for x in result:
  print("ARTICLE",x["slug"],"image DOM count",len(x["images"]))
  for im in x["images"][:6]:
      print("IMAGE",im.get("width"),im.get("height"),im.get("src","")[:250])
