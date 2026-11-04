#!/usr/bin/env python3
"""Find archival HPII covers in public Telegram channel posts by canonical Dzen URL.

Do not use Telegram previews or unrelated posts. Save diagnostics and matching
article-owned uploaded photographs only. This script cannot publish to any feed.
"""
from pathlib import Path
import json
import re
import html
from urllib.request import urlopen,Request
from urllib.parse import urlsplit
from io import BytesIO
from PIL import Image,ImageOps
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
entries=json.loads((ROOT/"registry/archive_batch5_candidates.json").read_text())["entries"]
rows=json.loads((ROOT/"news.json").read_text())
by_dzen={r["dzen_url"]:r for r in rows if r.get("dzen_url")}
targets={}
for e in entries:
    r=next((r for r in rows if r.get("dzen_id")==e["dzen_id"]),None)
    if r is None:continue
    with Image.open(ROOT/r["cover"]) as im:
        if im.width/im.height > 1.90:
            targets[e["dzen_url"]]=r
print("Dzen OG share cards needing real pictures:",len(targets),flush=True)

def get(url):
    with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"text/html,image/*"}),timeout=20) as f:
        return f.read(14_000_000)
results={}
last_before=None
for p in range(20):
    url="https://t.me/s/iipike"+(f"?before={last_before}" if last_before else "")
    try:
        soup=BeautifulSoup(get(url).decode("utf-8",errors="replace"),"html.parser")
    except Exception as exc:
        print("Telegram request failed",type(exc).__name__,str(exc)[:180],flush=True)
        break
    messages=soup.select(".tgme_widget_message[data-post]")
    print("Telegram page",p,"messages",len(messages),"matched",len(results),flush=True)
    ids=[]
    for msg in messages:
        pid=msg.get("data-post","")
        try: ids.append(int(pid.rsplit("/",1)[-1]))
        except Exception: continue
        hrefs={a.get("href","").split("#",1)[0] for a in msg.select("a[href]")}
        for orig,r in targets.items():
            if orig not in hrefs or orig in results:continue
            photo=msg.select_one(".tgme_widget_message_photo_wrap")
            style=(photo.get("style") or "") if photo else ""
            match=re.search(r'background-image:\s*url\([\'"]?(https?[^\'")]+)',html.unescape(style))
            if match:
                results[orig]={"telegram_message":pid,"image_url":html.unescape(match.group(1)), "slug":r["id"]}
                print("Matched exact Dzen article post",r["id"],pid,flush=True)
    if len(results)==len(targets):break
    if not ids:break
    least=min(ids)
    if last_before is not None and least>=last_before:break
    last_before=least
    if least<=1:break
recover=[]
for orig,r in targets.items():
    match=results.get(orig)
    if not match:
        recover.append({"slug":r["id"],"status":"telegram_post_not_found"})
        continue
    try:
        bits=get(match["image_url"])
        with Image.open(BytesIO(bits)) as image:
            pic=ImageOps.exif_transpose(image).convert("RGB")
            if pic.width<780 or pic.height<430 or not 1.60<pic.width/pic.height<1.95:
                raise ValueError("Unexpected dimensions "+str(pic.size))
            dst=ROOT/r["cover"]
            pic.save(dst,"WEBP",quality=93,method=4)
            recover.append({"slug":r["id"],"status":"telegram_photo_restored","width":pic.width,"height":pic.height,
                "post":match["telegram_message"],"source":match["image_url"],"local_path":r["cover"]})
            print("RESTORED",r["id"],pic.width,pic.height,flush=True)
    except Exception as exc:
        recover.append({"slug":r["id"],"status":"download_failure","why":type(exc).__name__+": "+str(exc)[:200]})
document={"targeted":len(targets),"matched":len(results),"restored":sum(x["status"]=="telegram_photo_restored" for x in recover),"items":recover}
(ROOT/"registry/batch5_telegram_photo_recovery.json").write_text(json.dumps(document,ensure_ascii=False,indent=2)+"\n")
print("Restored original-art Telegram photos:",document["restored"],"/",document["targeted"],flush=True)
