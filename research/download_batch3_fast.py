#!/usr/bin/env python3
"""Bounded concurrent restoration of the *published article's own* Dzen cover.

A missing image cannot be replaced by stock art. Downloads are isolated from
production and have no publishing / social-media side effects.
"""
import concurrent.futures as cf
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
batch = json.loads((ROOT/"research/batch3_candidates.json").read_text(encoding="utf-8"))["candidates"]
probe = {r["slug"]:r for r in json.loads((ROOT/"research/batch3_probe_results.json").read_text(encoding="utf-8"))["results"]}
dest = ROOT/"assets/imported"
dest.mkdir(exist_ok=True, parents=True)
OG = re.compile(r"^https://avatars\.dzeninfra\.ru/get-zen-pub-og/(\d+)/pub_([a-f0-9]{24})_([a-f0-9]{24})/optimize$")

def sources(item, source):
    dom = source["dom"]
    base = [
       im["src"] for im in dom.get("images",[])
       if "/get-zen_doc/" in im.get("src","")
       and "/scale_1200" in im.get("src","")
       and ("pub_"+item["dzen_id"]+"_") in im.get("src","")
    ]
    if not base:
        m = OG.fullmatch(dom.get("og_image") or "")
        if m and m.group(2)==item["dzen_id"]:
            base=["https://avatars.dzeninfra.ru/get-zen_doc/"+m.group(1)+"/pub_"+m.group(2)+"_"+m.group(3)+"/scale_1200"]
    if not base: raise ValueError("No image matching this original Dzen article")
    base = base[0]
    return [base.replace("/scale_1200",new) for new in ("/scale_2000","/scale_1200","/orig")]

def fetch(url):
    r = Request(url, headers={"User-Agent":"Mozilla/5.0","Accept":"image/*"})
    with urlopen(r,timeout=11) as response:
        data=response.read(13_000_000)
    with Image.open(BytesIO(data)) as i:
        pic=ImageOps.exif_transpose(i).convert("RGB")
        w,h=pic.size
        if not(w>=780 and h>=430 and 1.65 < w/h < 1.90):
            raise ValueError(f"Wrong landscape aspect or resolution: {w}x{h}")
        return pic

def one(item):
    slug=item["slug"]
    try:
        x=probe.get(slug)
        if not x or x.get("http_status")!=200 or x.get("dom",{}).get("og_title")!=item["title"]:
            raise ValueError("Unverified source page/title")
        fp=dest/(slug+".webp")
        if fp.exists():
            with Image.open(fp) as image: w,h=image.size
            return {"slug":slug,"status":"downloaded","cover":"assets/imported/"+fp.name,
                    "width":w,"height":h,"sha256":hashlib.sha256(fp.read_bytes()).hexdigest(),
                    "bytes":fp.stat().st_size,"url":"previously verified"}
        errs=[]
        for url in sources(item,x):
            try:
                pic=fetch(url)
                pic.save(fp,format="WEBP",quality=90,method=4)
                return {"slug":slug,"status":"downloaded","cover":"assets/imported/"+fp.name,
                    "width":pic.width,"height":pic.height,
                    "sha256":hashlib.sha256(fp.read_bytes()).hexdigest(),
                    "bytes":fp.stat().st_size,"url":url}
            except Exception as e:
                errs.append(type(e).__name__+": "+str(e)[:100])
        raise ValueError("Image source unavailable: "+"; ".join(errs))
    except Exception as e:
        return {"slug":slug,"status":"failed","why":str(e)[:650]}

with cf.ThreadPoolExecutor(max_workers=6) as executor:
    futures={executor.submit(one,item):item["slug"] for item in batch}
    results=[]
    for f in cf.as_completed(futures):
        value=f.result()
        print("ART", value["status"], value["slug"],str(value.get("width") or value.get("why"))[:170],flush=True)
        results.append(value)
results.sort(key=lambda x: next(i for i,b in enumerate(batch) if b["slug"]==x["slug"]))
out=ROOT/"research/batch3_cover_report.json"
out.write_text(json.dumps({"entries":results,"note":"Original article-owned image sources on Dzen, not generated artwork."},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("Authenticated original covers:",sum(x["status"]=="downloaded" for x in results),"/",len(results),flush=True)
