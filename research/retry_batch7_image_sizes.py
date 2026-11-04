#!/usr/bin/env python3
"""Repair only missing true Dzen article-owned artwork; never branded OG cards."""
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor,as_completed
from io import BytesIO
from pathlib import Path
from urllib.request import Request,urlopen
from PIL import Image,ImageOps

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/"research/batch7_cover_report.json"
report=json.loads(path.read_text(encoding="utf-8"))
probes={x["slug"]:x for x in json.loads((ROOT/"research/batch7_probe_results.json").read_text(encoding="utf-8"))["results"]}
candidates={x["slug"]:x for x in json.loads((ROOT/"research/batch7_candidates.json").read_text(encoding="utf-8"))["candidates"]}
missing=[x for x in report["entries"] if x["status"]!="downloaded"]
print("Original covers still missing",len(missing),flush=True)

def recover(row):
    slug=row["slug"]
    article=candidates[slug]
    capture=probes[slug]
    dom=capture.get("dom") or {}
    if capture.get("http_status")!=200 or capture.get("final_url")!=article["dzen_url"]:
        return row
    if "/pub_"+article["dzen_id"]+"_" not in (dom.get("og_image") or ""):
        return row
    imgurls=[x.get("src","") for x in dom.get("images",[])
             if "/pub_"+article["dzen_id"]+"_" in x.get("src","") and "get-zen_doc" in x.get("src","")]
    if not imgurls:
        print("NO ORIGINAL IMAGE REFERENCE",slug,flush=True)
        return row
    seen=set()
    best=None
    for uri in imgurls:
        prefix=uri.rsplit("/",1)[0]
        opts=["scale_2000","scale_1600","scale_1200","smart_crop_1200x676",
              "smart_crop_1200x675","smart_crop_800x450","smart_crop_516x290","orig"]
        for opt in opts:
            u=prefix+"/"+opt
            if u in seen:continue
            seen.add(u)
            try:
                with urlopen(Request(u,headers={"User-Agent":"Mozilla/5.0","Accept":"image/*"}),timeout=8) as response:
                    bits=response.read(12_000_000)
                with Image.open(BytesIO(bits)) as im:
                    picture=ImageOps.exif_transpose(im).convert("RGB")
                    w,h=picture.size
                    if w<500 or h<275 or not 1.65<w/h<1.86:
                        print("SKIP IMAGE WRONG SIZE/ASPECT",slug,opt,w,h,flush=True)
                        continue
                    if best is None or w*h>best[0]*best[1]:
                        best=(w,h,picture.copy(),u)
                    if w>=780 and h>=430:break
            except Exception as e:
                print("NOT AVAILABLE",slug,opt,type(e).__name__,flush=True)
        if best and best[0]>=780:break
    if best is None:return row
    w,h,img,url=best
    dest=ROOT/"assets/imported"/(slug+".webp")
    dest.parent.mkdir(parents=True,exist_ok=True)
    img.save(dest,"WEBP",quality=93,method=4)
    out={"slug":slug,"status":"downloaded","cover":"assets/imported/"+dest.name,
         "source":"dzen_article_image","source_url":url,"telegram_post":None,
         "width":w,"height":h,"bytes":dest.stat().st_size,
         "sha256":hashlib.sha256(dest.read_bytes()).hexdigest(),
         "resolution_class":"native_source_small" if w<780 else "regular"}
    print("RECOVERED",slug,w,h,url,flush=True)
    return out

with ThreadPoolExecutor(max_workers=4) as pool:
    lookup={fut.result()["slug"]:fut.result() for fut in as_completed([pool.submit(recover,row) for row in missing])}
report["entries"]=[lookup.get(x["slug"],x) for x in report["entries"]]
path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("TOTAL TRUE ORIGINAL COVERS",sum(x["status"]=="downloaded" for x in report["entries"]),"/",len(report["entries"]),flush=True)
