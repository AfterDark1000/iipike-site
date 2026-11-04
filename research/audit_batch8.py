#!/usr/bin/env python3
"""Audit all final HPII historic Dzen source pages: author, title, date, full text."""
import datetime as dt
import json,re
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[1]
source=json.loads((root/"research/batch8_probe_results.json").read_text(encoding="utf-8"))["results"]
candidates=json.loads((root/"research/batch8_candidates.json").read_text(encoding="utf-8"))["candidates"]
byid={x["slug"]:x for x in source}
checks=[]
for item in candidates:
    p=byid[item["slug"]]
    dom=p.get("dom") or {}
    main=dom.get("main") or ""
    title=(dom.get("og_title") or "").strip()
    date_list=[x.get("value") for x in dom.get("date_meta",[]) if x.get("key")=="datePublished"]
    date=date_list[0] if len(date_list)==1 and re.fullmatch(r"\d{4}-\d\d-\d\d",date_list[0] or "") else None
    desc=(dom.get("description") or "").strip()
    desc=desc.split("✍:",1)[-1].strip() if "✍:" in desc else desc
    at=-1
    for size in (160,120,90,60,40,30,24,14,10):
        if len(desc)>=size:
            i=main.find(desc[:size])
            if i>=0:
                at=i
                break
    # The usual public Dzen article end; never use content past it.
    end=main.find("\nПодпишитесь на канал,",at) if at>=0 else -1
    body=main[at:end].strip() if at>=0 and end>at else ""
    expected_day=None
    if item.get("source_instant"):
        moment=dt.datetime.fromisoformat(item["source_instant"].replace("Z","+00:00"))
        expected_day=moment.astimezone(ZoneInfo("Asia/Yekaterinburg")).date().isoformat()
    elif item.get("source_date"):
        expected_day=item["source_date"]
    identity=(p.get("http_status")==200 and p.get("final_url")==item["dzen_url"]
              and "/pub_"+item["dzen_id"]+"_" in (dom.get("og_image") or "")
              and "Хроники Пикирующего ИИ" in main[:1400])
    authoritative=identity and date is not None and bool(title) and (expected_day is None or expected_day==date)
    record={
        "research_slug":item["slug"],"dzen_id":item["dzen_id"],"dzen_url":item["dzen_url"],"kind":item["kind"],
        "original_page_confirmed":identity,"valid_source":authoritative,
        "title":title,"previous_title":item["title"],"title_log_matches":item.get("title")==title if item.get("title") else None,
        "day":date,"day_from_public_html":"meta[itemprop=datePublished]",
        "source_exact_utc":item.get("source_instant"),"original_time_known":bool(item.get("source_instant")),
        "original_body_start":at,"original_body_end":end,"original_body_chars":len(body),
        "original_body_paragraphs":len([t for t in body.split("\n\n") if t.strip()]),
        "body_start_sample":body[:150],"original_image_candidates":len((dom.get("images") or [])),
        "error":p.get("error")}
    checks.append(record)
    print("ARTICLE",item["kind"],item["dzen_id"],"identity",identity,"date",date,
          "title",repr(title),"body",len(body),"image_count",record["original_image_candidates"],flush=True)
(root/"research/batch8_source_audit.json").write_text(json.dumps({"batch":8,"records":checks},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("SUMMARY total",len(checks),"valid_source",sum(x["valid_source"] for x in checks),
      "full_body",sum(x["original_body_chars"]>=400 for x in checks),
      "no_body",sum(not x["original_body_chars"] for x in checks),flush=True)
