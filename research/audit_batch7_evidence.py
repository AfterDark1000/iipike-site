#!/usr/bin/env python3
"""Summarize original Dzen date-only evidence and locate full article boundaries."""
import json
from pathlib import Path
import re

root=Path(__file__).resolve().parents[1]
data=json.loads((root/"research/batch7_probe_results.json").read_text())["results"]
manifest=json.loads((root/"research/batch7_candidates.json").read_text())["candidates"]
by_slug={r["slug"]:r for r in data}
report=[]
for item in manifest:
    p=by_slug[item["slug"]]
    dom=p.get("dom") or {}
    dates=[x.get("value") for x in dom.get("date_meta",[]) if x.get("key")=="datePublished"]
    canonical_date=dates[0] if len(dates)==1 and re.fullmatch(r"2026-\d\d-\d\d",dates[0] or "") else None
    text=dom.get("main") or ""
    description=(dom.get("description") or "").strip()
    if "✍:" in description:
        description=description.split("✍:",1)[1].strip()
    pos=-1
    for n in (160,120,90,60,40,24,14):
        if len(description)>=n:
            pos=text.find(description[:n])
            if pos>=0:break
    stop=text.find("\nПодпишитесь на канал,",pos) if pos>=0 else -1
    body=text[pos:stop].strip() if pos>=0 and stop>pos else ""
    # For Dzen pages with a main Description that is not a verbatim lead:
    source_og=dom.get("og_title")
    original_verified=(
        p.get("http_status")==200 and p.get("final_url")==item["dzen_url"]
        and isinstance(source_og,str) and bool(source_og.strip())
        and "/pub_"+item["dzen_id"]+"_" in (dom.get("og_image") or "")
        and canonical_date is not None
    )
    entry={
        "slug":item["slug"],"dzen_id":item["dzen_id"],"dzen_url":item["dzen_url"],
        "log_title":item["title"],"source_og_title":source_og,
        "title_matches_old_log":source_og==item["title"],
        "original_page_verified":original_verified,
        "source_date":canonical_date,"date_evidence":"Dzen meta[itemprop=datePublished] (calendar day only)",
        "original_time_known":False,
        "description":description,"first_excerpt_at":pos,"text_footer_at":stop,
        "length_full_body":len(body),"paragraphs":len([v for v in body.split("\n\n") if v.strip()]),
        "first_body":body[:300],
        "main_start":text[:230],
        "error":p.get("error")
    }
    print("AUDIT",entry["slug"],"verified",original_verified,"title?",entry["title_matches_old_log"],
          "date",canonical_date,"body length",len(body),"body start index",pos,
          "body end",stop,flush=True)
    if source_og!=item["title"]:
        print("TITLE_MISMATCH",repr(item["title"]),"SOURCE",repr(source_og),flush=True)
    report.append(entry)
(root/"research/batch7_date_title_evidence.json").write_text(json.dumps({
    "schema_version":1,"batch":7,"records":report
},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("VERIFIED",sum(x["original_page_verified"] for x in report),
      "BODY LOCATED",sum(x["length_full_body"]>=400 for x in report),
      "LOG TITLE MATCHED",sum(x["title_matches_old_log"] for x in report),flush=True)
