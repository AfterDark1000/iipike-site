#!/usr/bin/env python3
"""Recover HPII's own artwork for Batch 8, never Dzen share-card images.

Primary: uploaded photo from our public Telegram crosspost whose text links to
the *exact* original Dzen URL. Secondary: article-owned get-zen_doc image URLs
observed on Dzen itself. Explicitly reject get-zen-pub-og and all stock art.
No publication and no social/Telegram API writes.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request,urlopen
import hashlib
import html
import json
import re
from PIL import Image, ImageOps
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
batch=json.loads((ROOT/"research/batch8_candidates.json").read_text(encoding="utf-8"))["candidates"]
probes={x["slug"]:x for x in json.loads((ROOT/"research/batch8_probe_results.json").read_text(encoding="utf-8"))["results"]}
outdir=ROOT/"assets/imported"
outdir.mkdir(exist_ok=True,parents=True)
targets={x["dzen_url"]:x for x in batch}
assert len(targets)==len(batch)==28
matched={}
before=None

def download(url,limit=14_000_000,timeout=22):
    with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"text/html,image/*"}),timeout=timeout) as response:
        raw=response.read(limit+1)
    if len(raw)>limit:raise ValueError("Resource too large")
    return raw

# Telegram archive contains the original cover photo uploaded by our own
# crossposter, separate from branded Dzen OpenGraph previews.
for page_number in range(50):
    url="https://t.me/s/iipike"+(f"?before={before}" if before else "")
    try:
        soup=BeautifulSoup(download(url).decode("utf-8",errors="replace"),"html.parser")
    except Exception as ex:
        print("TELEGRAM_ARCHIVE_UNAVAILABLE",type(ex).__name__,str(ex)[:200],flush=True)
        break
    messages=soup.select(".tgme_widget_message[data-post]")
    msgids=[]
    for message in messages:
        post=message.get("data-post","")
        try:msgids.append(int(post.rsplit("/",1)[-1]))
        except (ValueError,IndexError):continue
        refs={a.get("href","").split("#",1)[0] for a in message.select("a[href]")}
        matching=refs.intersection(targets)
        if not matching:continue
        photo=message.select_one(".tgme_widget_message_photo_wrap")
        style=(photo.get("style") or "") if photo else ""
        m=re.search(r'background-image:\s*url\([\'"]?(https?[^\'")]+)',html.unescape(style))
        if not m:continue
        photo_url=html.unescape(m.group(1))
        if urlsplit(photo_url).hostname not in ("cdn4.telesco.pe","cdn5.telesco.pe","cdn1.telesco.pe","cdn2.telesco.pe","cdn3.telesco.pe","cdn.telesco.pe"):
            continue
        for link in matching:
            matched[link]={"url":photo_url,"post":post}
    print("TELEGRAM",page_number,"matches",len(matched),"/",len(targets),flush=True)
    if len(matched)==len(targets):break
    if not msgids:break
    smallest=min(msgids)
    if before is not None and smallest>=before:break
    before=smallest
    if before<=1:break

def validate_and_save(item,bits,source_type,source_url,post=None):
    with Image.open(BytesIO(bits)) as im:
        image=ImageOps.exif_transpose(im).convert("RGB")
        w,h=image.size
        if w<780 or h<430 or not 1.65<w/h<1.86:
            raise ValueError(f"Not original 16:9 HPII landscape artwork: {w}x{h}")
        dest=outdir/(item["slug"]+".webp")
        image.save(dest,format="WEBP",quality=92,method=4)
        size=dest.stat().st_size
        if size<15_000:
            dest.unlink()
            raise ValueError("Image too small")
        return {"slug":item["slug"],"status":"downloaded","cover":"assets/imported/"+dest.name,
                "source":source_type,"source_url":source_url,"telegram_post":post,
                "width":w,"height":h,"bytes":size,
                "sha256":hashlib.sha256(dest.read_bytes()).hexdigest()}

def get_article_owned_dzen(item):
    p=probes.get(item["slug"],{})
    if p.get("http_status")!=200 or (item.get("title") and p.get("dom",{}).get("og_title")!=item["title"]):
        raise ValueError("Dzen original page not authenticated")
    images=(p.get("dom") or {}).get("images") or []
    for im in images:
        u=im.get("src","")
        if "get-zen_doc" not in u or "/pub_"+item["dzen_id"]+"_" not in u:
            continue
        if urlsplit(u).hostname!="avatars.dzeninfra.ru":
            continue
        base=u.rsplit("/",1)[0]
        for end in ("scale_1200","scale_2000","orig"):
            try:
                uri=base+"/"+end
                return validate_and_save(item,download(uri,timeout=12),"dzen_article_image",uri)
            except Exception as e:
                print("DZEN_CDN_FAILED",item["slug"],end,type(e).__name__,flush=True)
    raise ValueError("Matching original Dzen article image URL unavailable")

def one(item):
    try:
        copy=matched.get(item["dzen_url"])
        if copy:
            try:
                return validate_and_save(item,download(copy["url"],timeout=20),"telegram_original_photo",copy["url"],copy["post"])
            except Exception as e:
                print("TELEGRAM_PHOTO_FAILED",item["slug"],type(e).__name__,str(e)[:120],flush=True)
        return get_article_owned_dzen(item)
    except Exception as e:
        return {"slug":item["slug"],"status":"failed","reason":type(e).__name__+": "+str(e)[:320]}

with ThreadPoolExecutor(max_workers=5) as pool:
    fs={pool.submit(one,item):item["slug"] for item in batch}
    recovered={fut.result()["slug"]:fut.result() for fut in as_completed(fs)}
result=[recovered[item["slug"]] for item in batch]
for item in result: print("COVER",item["status"],item["slug"],item.get("source") or item.get("reason"),flush=True)
doc={"batch":6,"note":"No get-zen-pub-og or branded share cards; only article-matched HPII artwork.",
     "entries":result}
(ROOT/"research/batch8_cover_report.json").write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("Recovered true HPII covers:",sum(x["status"]=="downloaded" for x in result),"/",len(batch),flush=True)
