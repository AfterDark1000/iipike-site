#!/usr/bin/env python3
"""Try the article's own OG image after original-size CDN variants return 404.

Strictly tied to article Dzen ID. No stock/AI substitutes, no Dzen writes.
"""
import concurrent.futures as cf
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from urllib.request import Request,urlopen
from PIL import Image,ImageOps

ROOT=Path(__file__).resolve().parents[1]
candidate=json.loads((ROOT/"research/batch5_pool.json").read_text(encoding="utf-8"))["entries"]
probes={x["slug"]:x for x in json.loads((ROOT/"research/batch5_probe_results.json").read_text(encoding="utf-8"))["results"]}
path=ROOT/"research/batch5_cover_report.json"
doc=json.loads(path.read_text(encoding="utf-8"))
old={x["slug"]:x for x in doc["entries"]}
DIR=ROOT/"assets/imported"
DIR.mkdir(exist_ok=True,parents=True)
PATTERN=re.compile(r"^https://avatars\.dzeninfra\.ru/get-zen-pub-og/(\d+)/pub_([a-f0-9]{24})_([a-f0-9]{24})/optimize$")

def attempt(item):
    old_report=old.get(item["slug"],{})
    if old_report.get("status")=="downloaded":return old_report
    src=probes.get(item["slug"],{})
    if src.get("http_status")!=200 or src.get("dom",{}).get("og_title")!=item["title"]:
        return old_report
    url=(src.get("dom") or {}).get("og_image") or ""
    m=PATTERN.fullmatch(url)
    if not m or m.group(2)!=item["dzen_id"]:
        return old_report
    try:
        with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"image/*"}),timeout=14) as r:
            bits=r.read(12_000_000)
        with Image.open(BytesIO(bits)) as original:
            image=ImageOps.exif_transpose(original).convert("RGB")
            w,h=image.size
            if w<780 or h<430 or not 1.65<w/h<1.96:
                raise ValueError("Inappropriate cover proportions/resolution "+str(image.size))
            dest=DIR/(item["slug"]+".webp")
            image.save(dest,"WEBP",quality=90,method=4)
            report={"slug":item["slug"],"status":"downloaded","cover":"assets/imported/"+dest.name,
                "width":w,"height":h,"bytes":dest.stat().st_size,
                "sha256":hashlib.sha256(dest.read_bytes()).hexdigest(),
                "url":url,"source":"article-owned Dzen OG cover"}
            print("RECOVERED OG COVER",item["slug"],w,h,flush=True)
            return report
    except Exception as e:
        print("OG UNAVAILABLE",item["slug"],type(e).__name__,str(e)[:150],flush=True)
        return old_report

with cf.ThreadPoolExecutor(max_workers=6) as pool:
    result=list(pool.map(attempt,candidate))
doc["entries"]=result
doc["note"]="Only original images from article-owned Dzen CDN URLs; no substitutions."
path.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("Verified Dzen-owned article images after OG fallback:",sum(x.get("status")=="downloaded" for x in result),"/",len(result),flush=True)
