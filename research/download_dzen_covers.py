#!/usr/bin/env python3
"""Restore visual originals from the corresponding published Dzen article.

These are the *article's own* Dzen image URLs, not stock photos or new renders.
Download-only; never posts to Dzen/Telegram or changes production site.
"""
import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from PIL import Image, ImageOps

ROOT=Path(__file__).resolve().parents[1]
PROBE=json.loads((ROOT/"research/dzen_probe_results.json").read_text(encoding="utf-8"))
BATCH=json.loads((ROOT/"research/first10_candidates.json").read_text(encoding="utf-8"))
rows={r["slug"]:r for r in PROBE["results"]}
dest=ROOT/"assets/imported"
dest.mkdir(parents=True,exist_ok=True)
report=[]

def choose_cover(item,probe):
    raw=[img["src"] for img in probe.get("dom",{}).get("images",[])
         if "/get-zen_doc/" in img.get("src","")
         and "/scale_1200" in img.get("src","")
         and ("pub_"+item["dzen_id"]+"_") in img.get("src","")]
    if not raw and item["slug"] == "codex-git-server":
        # A verified Dzen document cover was present in the first successful
        # read-only probe, but this image is occasionally missing on reload.
        raw = ["https://avatars.dzeninfra.ru/get-zen_doc/271828/pub_6ae9af0cc44bda2203fe42ae_6ae9b391c4df40737e2e060a/scale_1200"]
    if not raw:
        raise ValueError("No article-owned original image URL found")
    src=raw[0]
    variants=[src.replace("/scale_1200","/orig"),
              src.replace("/scale_1200","/scale_2000"),src]
    best=None
    for url in variants:
        try:
            req=Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"image/*"})
            with urlopen(req,timeout=28) as response:
                data=response.read(15000000)
            with Image.open(io.BytesIO(data)) as img:
                pic=ImageOps.exif_transpose(img).convert("RGB")
                width,height=pic.size
                if width<780 or height<430 or not 1.65 < width/height < 1.9:
                    continue
                if best is None or width*height>best[0].width*best[0].height:
                    best=(pic.copy(),url)
        except (HTTPError,URLError,OSError,ValueError) as e:
            print("Image variant unavailable:",item["slug"],url.rsplit("/",1)[-1],str(e)[:100],flush=True)
    if best is None:
        raise ValueError("Could not download acceptable landscape cover image")
    return best

for item in BATCH["items"]:
    slug=item["slug"]; probe=rows.get(slug)
    existing = dest/(slug+".webp")
    if existing.is_file():
        with Image.open(existing) as im:
            w,h=im.size
        report.append({"slug":slug,"status":"downloaded","cover":"assets/imported/"+slug+".webp",
                       "width":w,"height":h,"bytes":existing.stat().st_size,
                       "sha256":hashlib.sha256(existing.read_bytes()).hexdigest(),
                       "url":"preserved_from_prior_download"})
        continue
    if not probe or probe.get("http_status")!=200 or probe.get("dom",{}).get("og_title")!=item["title"]:
        report.append({"slug":slug,"status":"failed","why":"Article source not confirmed"})
        continue
    try:
        pic,url=choose_cover(item,probe)
        target=dest/(slug+".webp")
        pic.save(target,format="WEBP",quality=90,method=6)
        digest=hashlib.sha256(target.read_bytes()).hexdigest()
        report.append({"slug":slug,"status":"downloaded","url":url,
                       "cover":"assets/imported/"+slug+".webp",
                       "width":pic.width,"height":pic.height,
                       "sha256":digest,"bytes":target.stat().st_size})
        print("COVER",slug,pic.size,url,flush=True)
    except Exception as e:
        report.append({"slug":slug,"status":"failed","why":str(e)})
        print("COVER FAILED",slug,str(e),flush=True)
out=ROOT/"research/dzen_cover_report.json"
out.write_text(json.dumps({"entries":report,"note":"Dzen-hosted originals (resized for hosting), not newly generated."},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("Downloaded",sum(e["status"]=="downloaded" for e in report),"of",len(report),"covers",flush=True)
