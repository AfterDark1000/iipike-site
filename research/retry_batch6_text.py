#!/usr/bin/env python3
"""Read-only retry of empty Dzen article bodies. No publication."""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright
from probe_batch6 import extract

ROOT=Path(__file__).resolve().parents[1]
dest=ROOT/"research/batch6_probe_results.json"
doc=json.loads(dest.read_text(encoding="utf-8"))
manifest=json.loads((ROOT/"research/batch6_candidates.json").read_text(encoding="utf-8"))
by_slug={x["slug"]:x for x in manifest["candidates"]}
res={x["slug"]:x for x in doc["results"]}
missing=[slug for slug,x in res.items() if not (x.get("dom") or {}).get("main")]
print("Originals with missing article body:",missing,flush=True)

async def main():
    async with async_playwright() as play:
        browser=await play.chromium.launch(headless=True,args=["--no-sandbox"])
        ctx=await browser.new_context(viewport={"width":1440,"height":940},locale="ru-RU",
             user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
        for slug in missing:
            item=by_slug[slug]
            for attempt in range(7):
                page=await ctx.new_page()
                try:
                    x=await extract(page,item)
                    if (x.get("http_status")==200 and
                        x.get("dom",{}).get("og_title")==item["title"] and
                        len(x.get("dom",{}).get("main") or "")>800):
                        res[slug]=x
                        print("RECOVERED",slug,"attempt",attempt+1,len(x["dom"]["main"]),flush=True)
                        break
                    await page.wait_for_timeout(2500)
                    main=await page.evaluate("document.querySelector('main')?.innerText || ''")
                    if (x.get("http_status")==200 and
                        x.get("dom",{}).get("og_title")==item["title"] and len(main)>800):
                        x["dom"]["main"]=main[:45000]
                        res[slug]=x
                        print("RECOVERED after JS load",slug,attempt+1,len(main),flush=True)
                        break
                    print("EMPTY",slug,"attempt",attempt+1,"http",x.get("http_status"),flush=True)
                finally:
                    await page.close()
                await asyncio.sleep(1.2)
        await browser.close()
    doc["results"]=[res[x["slug"]] for x in doc["results"]]
    dest.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Full original texts recovered:",sum(len((x.get("dom") or {}).get("main") or "")>800 for x in doc["results"]),"/",len(doc["results"]),flush=True)

if __name__=="__main__":
    asyncio.run(main())
