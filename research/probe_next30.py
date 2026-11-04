#!/usr/bin/env python3
"""Read-only extraction diagnostic for the next 30 original HPII Dzen stories.

Runs only on isolated research branch. Cannot publish articles or social posts.
Stores diagnostic texts and image candidates, not generated site pages.
"""
import asyncio
import datetime as dt
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "research" / "batch4_candidates.json"
OUTPUT = ROOT / "research" / "batch4_probe_results.json"

async def extract(page, item):
    url = item["dzen_url"]
    result = {"slug": item["slug"], "expected_url":url,"expected_title":item["title"]}
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(1500)
        result["http_status"] = response.status if response else None
        result["final_url"] = page.url
        result["page_title"] = await page.title()
        result["dom"] = await page.evaluate("""() => {
          function attr(sel,key='content'){let e=document.querySelector(sel);return e?e.getAttribute(key):null;}
          function txt(sel){let e=document.querySelector(sel);return e?e.innerText:null;}
          function stat(sel){let e=document.querySelector(sel);return e?{length:e.innerText.length,html_length:e.innerHTML.length}:null;}
          let imgs=Array.from(document.querySelectorAll('img')).map(i=>({alt:i.alt,src:i.currentSrc||i.src,width:i.naturalWidth,height:i.naturalHeight})).filter(i=>i.width>200||i.height>200).slice(0,30);
          return {
            description:attr('meta[name="description"]'),
            og_image:attr('meta[property="og:image"]'),
            og_title:attr('meta[property="og:title"]'),
            published:attr('meta[property="article:published_time"]'),
            article:txt('article'),
            article_body:txt('[itemprop="articleBody"]'),
            main:txt('main'),
            body:document.body?document.body.innerText.slice(0,45000):'',
            selectors:{article:stat('article'),itemprop:stat('[itemprop="articleBody"]'),main:stat('main')},
            images:imgs,
            external_links:Array.from(document.querySelectorAll('main a[href]')).map(a=>({text:a.innerText?.trim().slice(0,150),href:a.href})).filter(a=>a.href?.startsWith('https:')&&!a.href.includes('dzen.ru')).slice(0,60),
            headings:Array.from(document.querySelectorAll('main h1,main h2,main h3')).map(x=>({tag:x.tagName,text:x.innerText?.trim()})).slice(0,35)
          };
        }""")
        result["dom"]["article"] = (result["dom"]["article"] or "")[:45000]
        result["dom"]["article_body"] = (result["dom"]["article_body"] or "")[:45000]
        result["dom"]["main"] = (result["dom"]["main"] or "")[:45000]
    except Exception as e:
        result["error"] = type(e).__name__ + ": " + str(e)[:600]
    return result

async def main():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("playwright package missing", file=sys.stderr)
        raise
    manifest=json.loads(INPUT.read_text(encoding="utf-8"))
    candidates=manifest["candidates"]
    selected=candidates
    output=[]
    async with async_playwright() as play:
        browser=await play.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx=await browser.new_context(viewport={"width":1366,"height":900}, locale="ru-RU",
                                      user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
        for item in selected:
            page=await ctx.new_page()
            print("READ-ONLY probe",item["slug"],item["dzen_url"],flush=True)
            value=await extract(page,item)
            print("RESULT",item["slug"],value.get("http_status"),value.get("final_url"),
                  len((value.get("dom") or {}).get("body") or ""),
                  "article",len((value.get("dom") or {}).get("article") or ""),
                  "og",((value.get("dom") or {}).get("og_image") or "")[:120],flush=True)
            output.append(value)
            await page.close()
        await browser.close()
    OUTPUT.write_text(json.dumps({
      "captured_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
      "publication_permission":"NONE; diagnostic only", "results":output
    },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Diagnostic stored, read-only. No article has been published.",flush=True)

if __name__=="__main__":
    asyncio.run(main())
