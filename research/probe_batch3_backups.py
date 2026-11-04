#!/usr/bin/env python3
"""Look for one historically verified alternative with complete Dzen text and cover."""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright
from probe_next30 import extract

ROOT=Path(__file__).resolve().parents[1]
candidates=json.loads((ROOT/"research/batch3_backup_candidates.json").read_text(encoding="utf-8"))["candidates"]
out=ROOT/"research/batch3_backup_verified.json"

async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=["--no-sandbox"])
        ctx=await browser.new_context(viewport={"width":1366,"height":900},locale="ru-RU",
           user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
        chosen=None
        for item in candidates:
            for retry in range(3):
                page=await ctx.new_page()
                try:
                    result=await extract(page,item)
                    body=(result.get("dom") or {}).get("main") or ""
                    images=(result.get("dom") or {}).get("images") or []
                    good_images=[x for x in images if "pub_"+item["dzen_id"]+"_" in x.get("src","")
                        and "/get-zen_doc/" in x.get("src","")
                        and "/scale_1200" in x.get("src","")]
                    print("BACKUP",item["slug"],"attempt",retry+1,"status",result.get("http_status"),
                          "length",len(body),"article-owned covers",len(good_images),flush=True)
                    if (result.get("http_status")==200
                         and result.get("dom",{}).get("og_title")==item["title"]
                         and len(body)>900 and good_images):
                        chosen={"candidate":item,"probe":result}
                        break
                finally:
                    await page.close()
                await asyncio.sleep(1)
            if chosen:break
        await browser.close()
    if not chosen:
        raise SystemExit("No source-and-original-cover verified substitute; leave batch short.")
    out.write_text(json.dumps(chosen,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("SELECTED",chosen["candidate"]["slug"],flush=True)

if __name__=="__main__":asyncio.run(main())
