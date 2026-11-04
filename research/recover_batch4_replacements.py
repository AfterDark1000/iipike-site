#!/usr/bin/env python3
"""Fill five unavailable-cover slots with source-verified HPII originals.

Never invent artwork or modify Dzen. Keep failed originals in deferred backlog.
Only edit isolated archive branch and save exact source evidence.
"""
import asyncio
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.request import Request,urlopen
from PIL import Image,ImageOps
from playwright.async_api import async_playwright
from probe_next30 import extract

ROOT=Path(__file__).resolve().parents[1]
manifest_path=ROOT/"research/batch4_candidates.json"
probe_path=ROOT/"research/batch4_probe_results.json"
cover_path=ROOT/"research/batch4_cover_report.json"
alt_path=ROOT/"research/batch4_fallback_candidates.json"
deferred_path=ROOT/"research/batch4_deferred_originals.json"
art_dir=ROOT/"assets/imported"
art_dir.mkdir(exist_ok=True,parents=True)
manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
probes=json.loads(probe_path.read_text(encoding="utf-8"))
reports=json.loads(cover_path.read_text(encoding="utf-8"))
alternates=json.loads(alt_path.read_text(encoding="utf-8"))["candidates"]
catalog={x["dzen_id"]:x for x in json.loads(
 (ROOT/"data/editorial_full_catalog_snapshot.json").read_text(encoding="utf-8"))["entries"]}
already=json.loads((ROOT/"news.json").read_text(encoding="utf-8"))
included_ids={x.get("dzen_id") for x in already}
included_ids.update(x.get("dzen_id") for x in manifest["candidates"])
failed={x["slug"] for x in reports["entries"] if x["status"]!="downloaded"}
missing=[x for x in manifest["candidates"] if x["slug"] in failed]
print("Cover slots needing source-verified substitutes:",[x["slug"] for x in missing],flush=True)
assert len(failed)==len(missing)==5
OG=re.compile(r"^https://avatars\.dzeninfra\.ru/get-zen-pub-og/(\d+)/pub_([a-f0-9]{24})_([a-f0-9]{24})/optimize$")

def source_urls(item,probe):
    dom=probe["dom"]
    found=[x["src"] for x in dom.get("images",[])
           if "/get-zen_doc/" in x.get("src","")
           and "pub_"+item["dzen_id"]+"_" in x.get("src","")
           and "/scale_1200" in x["src"]]
    if not found:
        m=OG.fullmatch(dom.get("og_image") or "")
        if m and m.group(2)==item["dzen_id"]:
            found=["https://avatars.dzeninfra.ru/get-zen_doc/"+m.group(1)+"/pub_"+m.group(2)+"_"+m.group(3)+"/scale_1200"]
    if not found:
        raise ValueError("No article-owned Dzen image identifier")
    url=found[0]
    return [url.replace("/scale_1200",m) for m in ["/scale_1200","/scale_2000","/orig"]]

def fetch_original(item,probe):
    errors=[]
    for url in source_urls(item,probe):
        try:
            with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"image/*"}),timeout=12) as r:
                bits=r.read(14000000)
            with Image.open(io.BytesIO(bits)) as raw:
                im=ImageOps.exif_transpose(raw).convert("RGB")
                if im.width<780 or im.height<430 or not 1.65<im.width/im.height<1.90:
                    raise ValueError("Image dimensions/aspect not suitable: "+str(im.size))
                dest=art_dir/(item["slug"]+".webp")
                im.save(dest,format="WEBP",quality=90,method=4)
                return {"slug":item["slug"],"status":"downloaded","cover":"assets/imported/"+dest.name,
                        "width":im.width,"height":im.height,"bytes":dest.stat().st_size,
                        "sha256":hashlib.sha256(dest.read_bytes()).hexdigest(),"url":url}
        except Exception as exc:
            errors.append(type(exc).__name__+":"+str(exc)[:110])
    raise ValueError("Original Dzen cover unavailable: "+"; ".join(errors))

def body_valid(item,p):
    if p.get("http_status")!=200 or (p.get("dom") or {}).get("og_title")!=item["title"]:
        return False
    text=(p.get("dom") or {}).get("main") or ""
    original=item["excerpt"].strip()
    start=-1
    for n in (120,90,70,50,35,24,18,12):
        if len(original)>=n:
            start=text.find(original[:n])
            if start>=0:break
    end=text.find("\nПодпишитесь на канал,",start)
    return start>=0 and start<1800 and end>start and len(text[start:end])>=650

async def run():
    good=[]
    async with async_playwright() as play:
        browser=await play.chromium.launch(headless=True,args=["--no-sandbox"])
        context=await browser.new_context(viewport={"width":1440,"height":940},locale="ru-RU",
          user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
        for item in alternates:
            if len(good)>=len(missing):break
            if item["dzen_id"] in included_ids:continue
            entry=catalog[item["dzen_id"]]
            assert entry["dzen_url"]==item["dzen_url"] and entry["title"]==item["title"]
            assert entry["url_evidence"]=="recorded_in_editorial_archive" and entry["title_evidence"]=="recorded"
            found=None
            for attempt in range(4):
                page=await context.new_page()
                try:
                    p=await extract(page,item)
                    if body_valid(item,p):
                        found=p;break
                    print("No full text",item["slug"],"attempt",attempt+1,flush=True)
                finally:
                    await page.close()
                await asyncio.sleep(1)
            if found is None:continue
            try:
                art=fetch_original(item,found)
                print("FOUND",item["slug"],art["width"],art["height"],flush=True)
                good.append((item,found,art))
                included_ids.add(item["dzen_id"])
            except Exception as e:
                print("COVER UNAVAILABLE",item["slug"],str(e)[:400],flush=True)
        await browser.close()
    print("Approved substitute source/cover pairs:",len(good),"/",len(missing),flush=True)
    if len(good)!=len(missing):
        raise SystemExit("Insufficient verified substitutes; never publish partial batch as 30.")
    manifest["candidates"]=[x for x in manifest["candidates"] if x["slug"] not in failed]+[
        {**item,"status":"candidate","full_text":"verified_against_dzen","original_cover":"recovered"} for item,_,_ in good
    ]
    probes["results"]=[x for x in probes["results"] if x["slug"] not in failed]+[p for _,p,_ in good]
    reports["entries"]=[x for x in reports["entries"] if x["slug"] not in failed]+[cover for _,_,cover in good]
    assert len(manifest["candidates"])==len(probes["results"])==len(reports["entries"])==30
    deferred_path.write_text(json.dumps({
        "deferred_due_to_missing_original_cover":missing,
        "note":"Do not lose original articles. Their Dzen publications were left unchanged.",
    },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    for file,data in ((manifest_path,manifest),(probe_path,probes),(cover_path,reports)):
        file.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    asyncio.run(run())
