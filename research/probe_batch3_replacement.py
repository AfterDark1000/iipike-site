#!/usr/bin/env python3
"""Read one additional original Dzen article after a missing-cover replacement.

Never publishes posts or modifies production. The previous 29 verified source
records are preserved unchanged.
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright
from probe_next30 import extract

ROOT=Path(__file__).resolve().parents[1]
datafile=ROOT/"research/batch3_probe_results.json"
batch=json.loads((ROOT/"research/batch3_candidates.json").read_text(encoding="utf-8"))["candidates"]
data=json.loads(datafile.read_text(encoding="utf-8"))
known={x["slug"]:x for x in data["results"]}
expected={x["slug"] for x in batch}
missing=[x for x in batch if x["slug"] not in known]
assert len(missing)==1, f"Exactly one replacement expected, got {len(missing)}"
article=missing[0]
async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=["--no-sandbox"])
        context=await browser.new_context(viewport={"width":1366,"height":900},locale="ru-RU",
          user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
        page=await context.new_page()
        res=await extract(page,article)
        print("Replaced by",article["slug"],res.get("http_status"),res.get("dom",{}).get("og_title"),len((res.get("dom") or {}).get("main") or ""),flush=True)
        await browser.close()
        assert res.get("http_status")==200 and res.get("dom",{}).get("og_title")==article["title"],"Source/title verification failed"
        assert len((res.get("dom") or {}).get("main") or "")>850,"No complete article recovered"
        known[article["slug"]]=res
        data["results"]=[known[x["slug"]] for x in batch]
        assert len(data["results"])==30
        datafile.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
if __name__=="__main__":asyncio.run(main())
