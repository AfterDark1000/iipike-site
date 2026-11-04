#!/usr/bin/env python3
"""Restore native Krea artwork from its own 1448x1086 upload and Dzen smart crop.

Source identity must match article ID; brute-force compare vertical offsets at
thumbnail resolution before committing a full-res 16:9 crop. No resynthesis.
"""
import hashlib,json
from io import BytesIO
from pathlib import Path
from urllib.request import Request,urlopen
from PIL import Image,ImageOps,ImageChops,ImageStat
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/"research/batch8_cover_report.json"
doc=json.loads(p.read_text(encoding="utf-8"))
candidates=json.loads((ROOT/"research/batch8_candidates.json").read_text(encoding="utf-8"))["candidates"]
items={x["slug"]:x for x in candidates}
target=[r for r in doc["entries"] if r["slug"].startswith("krea-3-obeschaet")]
assert len(target)==1
row=target[0]
assert row["status"]=="downloaded" and row["source"]=="dzen_article_image"
ref=row["source_url"]
assert ref.endswith("/smart_crop_516x290")
assert "/pub_"+items[row["slug"]]["dzen_id"]+"_" in ref
url=ref.rsplit("/",1)[0]+"/orig"
with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"image/*"}),timeout=20) as response:
    buf=response.read(10_000_000)
with Image.open(BytesIO(buf)) as im:
    full=ImageOps.exif_transpose(im).convert("RGB")
fw,fh=full.size
assert fw>=1000 and fh>=800 and fw/fh<1.60,(fw,fh)
path=ROOT/row["cover"]
with Image.open(path) as im:
    thumbnail=im.convert("RGB")
tw,th=thumbnail.size
assert 500<=tw<=600 and 270<=th<=320
scale=fw/tw
down_h=round(fh/scale)
reduced=full.resize((tw,down_h),Image.Resampling.LANCZOS)
error,y_best=float("inf"),None
for y in range(down_h-th+1):
    sample=reduced.crop((0,y,tw,y+th))
    difference=ImageChops.difference(sample,thumbnail)
    score=sum(ImageStat.Stat(difference).mean)/3
    if score<error:
        error,y_best=score,y
print("NATIVE_CROP_CONFIDENCE",round(error,2),"top",y_best,"original",fw,fh,"thumbnail",tw,th,flush=True)
if error>35:raise ValueError("Crop alignment too uncertain for original artwork")
new_h=round(fw*9/16)
top=max(0,min(fh-new_h,round((y_best+th/2)*scale-new_h/2)))
image=full.crop((0,top,fw,top+new_h))
assert 1.75<fw/new_h<1.81
image.save(path,"WEBP",quality=93,method=4)
row.update({"width":fw,"height":new_h,"bytes":path.stat().st_size,
    "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
    "source":"dzen_article_original_native_crop","source_url":url,
    "crop_verified_against":ref,"crop_comparison_mean_rgb_error":round(error,2),
    "resolution_class":"native_cropped_from_original"})
p.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
assert len(doc["entries"])==28
assert all(x["status"]=="downloaded" and x["width"]>=780 and x["height"]>=430 for x in doc["entries"])
print("VERIFIED: 28 / 28 original covers full resolution",flush=True)
