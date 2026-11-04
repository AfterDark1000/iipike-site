#!/usr/bin/env python3
"""Select precisely thirty historical stories with matched Dzen text and own cover.

No rewriting, invented dates or alternative artwork. Does not publish.
"""
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
manifest=ROOT/"research/batch5_candidates.json"
orig=json.loads(manifest.read_text(encoding="utf-8"))
pool=orig["candidates"]
index={x["dzen_id"]:x for x in json.loads((ROOT/"data/editorial_full_catalog_snapshot.json").read_text(encoding="utf-8"))["entries"]}
published=json.loads((ROOT/"news.json").read_text(encoding="utf-8"))
existing={x.get("dzen_id") for x in published}
probes={x["slug"]:x for x in json.loads((ROOT/"research/batch5_probe_results.json").read_text(encoding="utf-8"))["results"]}
covers={x["slug"]:x for x in json.loads((ROOT/"research/batch5_cover_report.json").read_text(encoding="utf-8"))["entries"]}
selected=[]; deferred=[]
for item in pool:
    try:
        source=index[item["dzen_id"]]
        if item["dzen_id"] in existing:
            raise ValueError("Already on website")
        if any(item[k]!=source[k] for k in ("title","dzen_url","published_at_utc")):
            raise ValueError("Editorial source provenance mismatch")
        if source["title_evidence"]!="recorded" or source["url_evidence"]!="recorded_in_editorial_archive":
            raise ValueError("Unverified historical metadata")
        p=probes.get(item["slug"],{})
        if p.get("http_status")!=200 or (p.get("dom") or {}).get("og_title")!=item["title"]:
            raise ValueError("Original page title / HTTP status does not match")
        text=(p.get("dom") or {}).get("main") or ""
        excerpt=(item["excerpt"] or "").strip()
        pos=-1
        for n in (120,90,70,50,35,24,18,12):
            if len(excerpt)>=n:
                pos=text.find(excerpt[:n])
                if pos>=0: break
        end=text.find("\nПодпишитесь на канал,",pos)
        if pos<0 or pos>1800 or end<=pos or end-pos<650:
            raise ValueError("Cannot delimit full original source body")
        blocks=[b.strip() for b in text[pos:end].split("\n\n") if b.strip()]
        if not 2<=len(blocks)<=70: raise ValueError("Original paragraph structure invalid")
        c=covers.get(item["slug"],{})
        if c.get("status")!="downloaded" or not (ROOT/c.get("cover","")).is_file():
            raise ValueError("Original landscape Dzen cover not retrieved")
        if len(selected)<30:
            selected.append(item)
        else:
            deferred.append({"dzen_id":item["dzen_id"],"title":item["title"],"reason":"Valid reserve; not selected"})
    except (ValueError,KeyError,TypeError) as e:
        deferred.append({"dzen_id":item["dzen_id"],"title":item["title"],"reason":str(e)})
print("Verified original text + artwork:",len(selected),"of",len(pool),flush=True)
# This is *not* a publish-on-failure workflow. Gate before changing content.
report={"requested":30,"verified":len(selected),"deferred":deferred,
        "note":"Deferred entries remain in the original Dzen archive; no substitute artwork or fabricated prose."}
(ROOT/"research/batch5_selection_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
if len(selected)!=30:
    raise SystemExit("Not enough verified articles. Leave public site unchanged.")
orig["candidates"]=selected
manifest.write_text(json.dumps(orig,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
chosen={x["slug"] for x in selected}
for item in pool:
    if item["slug"] not in chosen:
        path=ROOT/"assets/imported"/(item["slug"]+".webp")
        if path.exists():path.unlink()
# Update the original PR selection to show only source-proven final articles.
path=ROOT/"registry/archive_batch5_candidates.json"
previous=json.loads(path.read_text(encoding="utf-8"))
previous["status"]="selected_for_review_not_yet_published"
previous["entries"]=[{k:item[k] for k in ("dzen_id","title","dzen_url","published_at_utc")} for item in selected]
path.write_text(json.dumps(previous,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("Selected IDs:",[x["dzen_id"] for x in selected],flush=True)
