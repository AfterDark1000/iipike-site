#!/usr/bin/env python3
"""Recover the original Dzen feed cover, *not* its branded OpenGraph share card.

Only article-owned feedData image URL is accepted, matched by 24-hex Dzen ID.
This is a repair-only workflow: it cannot publish to the website or social accounts.
"""
import asyncio
import json
import html
import re
import io
import hashlib
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request,urlopen
from PIL import Image,ImageOps
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]
items=json.loads((ROOT/"research/batch5_og_diagnostic.json").read_text())
published={x["dzen_id"] for x in json.loads((ROOT/"registry/archive_batch5_candidates.json").read_text())["entries"]}
need={x["dzen_id"]:x for x in items if x["dzen_id"] in published}
print("Need original feed covers:",len(need),flush=True)
found={}
decoder=json.JSONDecoder()
def decode_feed(source):
    for candidate in [source,html.unescape(source),source.replace('&quot;','"')]:
        for match in re.finditer(r'["\\]feedData["\\]\s*:\s*',candidate):
            try: doc,_=decoder.raw_decode(candidate[match.end():])
            except (ValueError,TypeError): continue
            if not isinstance(doc,dict):continue
            for item in doc.get("items",[]):
                if not isinstance(item,dict) or item.get("type")!="article":continue
                ident=str(item.get("id",""))
                if ident not in need:continue
                img=item.get("image") or {}
                template=img.get("urlTemplate") or ""
                namespace=img.get("namespace") or ""
                if not template or not namespace:continue
                u=template.replace("{namespace}",namespace).replace("{size}","scale_1200")
                if (urlsplit(u).hostname not in ("avatars.dzeninfra.ru","avatars.mds.yandex.net")
                    or "get-zen_doc" not in u):
                    continue
                if "/pub_"+ident+"_" not in u:continue
                found[ident]={"title":item.get("title",""),"url":u,"page":item.get("shareLink","")}
    return found

async def main():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,args=["--no-sandbox"])
        context=await browser.new_context(locale="ru-RU",viewport={"width":1440,"height":980})
        page=await context.new_page()
        await page.goto("https://dzen.ru/iipike?tab=articles",wait_until="domcontentloaded",timeout=45000)
        last=0
        for step in range(85):
            decode_feed(await page.content())
            if step%5==0: print("Scroll",step,"feed covers matched",len(found),"/",len(need),flush=True)
            if len(found)==len(need):break
            await page.evaluate("window.scrollBy(0, 2400)")
            await page.wait_for_timeout(800)
            if len(found)==last and step>=50: pass
            last=len(found)
        await browser.close()
    results=[]
    out=ROOT/"assets/imported"
    for id,entry in need.items():
        source=found.get(id)
        if source is None:
            results.append({"dzen_id":id,"slug":entry["slug"],"status":"not_in_public_feed_capture"})
            continue
        error=""
        for suffix in ["scale_1200","scale_2000","orig"]:
            url=re.sub(r"/scale_1200$", "/"+suffix, source["url"])
            try:
                with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"image/*"}),timeout=15) as response:
                    bits=response.read(12_000_000)
                with Image.open(io.BytesIO(bits)) as raw:
                    pic=ImageOps.exif_transpose(raw).convert("RGB")
                    w,h=pic.size
                    if w<780 or h<430 or not 1.65<w/h<1.95:
                        raise ValueError("Dimensions not plausible: "+str(pic.size))
                    path=out/(entry["slug"]+".webp")
                    pic.save(path,"WEBP",quality=90,method=4)
                    results.append({"dzen_id":id,"slug":entry["slug"],"status":"original_restored",
                        "source":"Dzen public channel feedData article image",
                        "url":url,"width":w,"height":h,"bytes":path.stat().st_size,
                        "sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
                    print("ORIGINAL RESTORED",entry["slug"],w,h,flush=True)
                    break
            except Exception as e:
                error=type(e).__name__+": "+str(e)[:130]
        else:
            results.append({"dzen_id":id,"slug":entry["slug"],"status":"original_unavailable","source_url":source["url"],"error":error})
    (ROOT/"research/batch5_feed_cover_results.json").write_text(json.dumps({
        "targeted_og_count":len(need),"found_feed_url":len(found),
        "restored":sum(r["status"]=="original_restored" for r in results),
        "results":results},ensure_ascii=False,indent=2)+"\n")
    print("Restored:",sum(r["status"]=="original_restored" for r in results),"/",len(need),flush=True)

if __name__=="__main__":
    asyncio.run(main())
