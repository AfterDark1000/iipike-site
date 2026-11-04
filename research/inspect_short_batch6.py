#!/usr/bin/env python3
"""Read-only QA of two unusually short *original* Dzen articles in batch six."""
import json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
data={r["slug"]:r for r in json.loads((R/"research/batch6_probe_results.json").read_text(encoding="utf-8"))["results"]}
items=json.loads((R/"research/batch6_candidates.json").read_text(encoding="utf-8"))["candidates"]
for item in items:
    if item["dzen_id"] not in ("6ad63ced7267ec5b95fec6b4","6ad63a9747711c346b04c5d3"):
        continue
    page=data[item["slug"]]
    dom=page.get("dom") or {}
    text=dom.get("main") or ""
    excerpt=item["excerpt"].strip()
    first=-1
    for n in (120,90,70,50,35,24,18,12):
        if len(excerpt)<n:continue
        first=text.find(excerpt[:n])
        if first>=0:break
    last=text.find("\nПодпишитесь на канал,",first)
    original=text[first:last].strip() if first>=0 and last>first else ""
    paras=[x.strip() for x in original.split("\n\n") if x.strip()]
    print("=== VERIFIED DZEN ORIGINAL",item["title"],"===")
    print("HTTP:",page.get("http_status"),"OG_title_matches:",dom.get("og_title")==item["title"])
    print("Introduction:",first,"Footer:",last,"Length:",len(original),"Paragraphs:",len(paras))
    print("SOURCE_START")
    print(original)
    print("SOURCE_END")
