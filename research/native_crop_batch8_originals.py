#!/usr/bin/env python3
"""Restore native-res HPII cover crops from Dzen's own original uploaded images.

For a 1536x1024 original and its Dzen smart_crop_516x290, locate the exact
vertical crop by comparing the source's downsized slices against its thumbnail.
No upscaling, generative content, text edits, or branded OpenGraph cards.
"""
from io import BytesIO
from pathlib import Path
import json
import hashlib
from urllib.request import Request,urlopen
from PIL import Image, ImageOps, ImageStat, ImageChops

ROOT=Path(__file__).resolve().parents[1]
p=ROOT/"research/batch8_cover_report.json"
doc=json.loads(p.read_text(encoding="utf-8"))
success=0
for row in doc["entries"]:
    if row.get("status")!="downloaded" or row.get("source")!="dzen_article_image":continue
    if row.get("width",0)>=780:continue
    u=row.get("source_url","")
    if "get-zen_doc/" not in u or not u.endswith("/smart_crop_516x290"):
        print("SKIP NOT ORIGINAL SMARTCROP",row["slug"],flush=True)
        continue
    original_url=u.rsplit("/",1)[0]+"/orig"
    try:
        with urlopen(Request(original_url,headers={"User-Agent":"Mozilla/5.0","Accept":"image/*"}),timeout=20) as h:
            raw=h.read(12_000_000)
        with Image.open(BytesIO(raw)) as im:
            original=ImageOps.exif_transpose(im).convert("RGB")
        if original.size!=(1536,1024):
            print("SKIP UNEXPECTED ORIGINAL DIMENSIONS",row["slug"],original.size,flush=True)
            continue
        target_path=ROOT/row["cover"]
        with Image.open(target_path) as im:
            reference=im.convert("RGB").resize((516,290),Image.Resampling.LANCZOS)
        small=original.resize((516,344),Image.Resampling.LANCZOS)
        best=(float("inf"),-1)
        for y in range(55):
            cand=small.crop((0,y,516,y+290))
            delta=ImageChops.difference(reference,cand)
            err=sum(ImageStat.Stat(delta).mean)/3
            if err<best[0]:best=(err,y)
        score,y=best
        print("CROP_MATCH",row["slug"],"meanRGBdiff",round(score,2),"smallOffset",y,flush=True)
        if score>33:
            print("REFUSE_UNCERTAIN_IMAGE_MATCH",row["slug"],flush=True)
            continue
        full_h=864
        offset=max(0,min(1024-full_h,round(y*1024/344)))
        art=original.crop((0,offset,1536,offset+full_h))
        art.save(target_path,"WEBP",quality=92,method=4)
        row.update({"width":1536,"height":864,"bytes":target_path.stat().st_size,
            "sha256":hashlib.sha256(target_path.read_bytes()).hexdigest(),
            "source":"dzen_article_original_native_crop",
            "source_url":original_url,
            "crop_verified_against":"Dzen article-owned smart_crop_516x290",
            "crop_comparison_mean_rgb_error":round(score,2),
            "resolution_class":"native_cropped_from_original"})
        success+=1
    except Exception as e:
        print("ORIGINAL_NATIVE_CROP_FAILED",row["slug"],type(e).__name__,str(e)[:200],flush=True)
p.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("HIGH RES ART RESTORED",success,flush=True)
print("TOTAL ORIGINALS",sum(x["status"]=="downloaded" for x in doc["entries"]),
      "HIGH RES",sum(x.get("status")=="downloaded" and x.get("width",0)>=780 for x in doc["entries"]),flush=True)
