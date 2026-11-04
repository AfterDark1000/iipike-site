#!/usr/bin/env python3
"""Targeted read-only retry for missing Dzen cover DOM or original article body."""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright
from probe_next30 import extract

ROOT=Path(__file__).resolve().parents[1]
report=json.loads((ROOT/"research/batch4_cover_report.json").read_text(encoding="utf-8"))
missing={x["slug"] for x in report["entries"] if x["status"]!="downloaded"}
probe_file=ROOT/"research/batch4_probe_results.json"
data=json.loads(probe_file.read_text(encoding="utf-8"))
manifest=json.loads((ROOT/"research/batch4_candidates.json").read_text(encoding="utf-8"))
items={x["slug"]:x for x in manifest["candidates"]}
initial={x["slug"]:x for x in data["results"]}
missing.update(x["slug"] for x in data["results"] if not (x.get("dom") or {}).get("main"))

async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=["--no-sandbox"])
        ctx=await browser.new_context(viewport={"width":1450,"height":960},
          locale="ru-RU",user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
        for slug in sorted(missing):
            item=items[slug];old=initial[slug]
            print("Retry source",slug,flush=True)
            best=old
            for n in range(3):
                page=await ctx.new_page()
                try:
                    outcome=await extract(page,item)
                    await page.evaluate("window.scrollTo(0, Math.max(150, document.body.scrollHeight/4))")
                    await page.wait_for_timeout(1500)
                    images=await page.evaluate("""() => Array.from(document.querySelectorAll('img')).map(i=>({
                        src:i.currentSrc||i.src,width:i.naturalWidth,height:i.naturalHeight,alt:i.alt
                      })).filter(x=>x.width>250||x.height>200).slice(0,35)""")
                    if outcome.get("dom"):
                        prev=outcome["dom"].get("images") or []
                        outcome["dom"]["images"]=list({x["src"]:x for x in prev+images}.values())
                    if outcome.get("http_status")==200 and outcome.get("dom",{}).get("og_title")==item["title"]:
                        if len(outcome.get("dom",{}).get("main") or "")>=len(best.get("dom",{}).get("main") or ""):
                            best=outcome
                        else:
                            # Preserve more complete article text, but merge recovered cover refs.
                            original_images=(best.get("dom") or {}).get("images") or []
                            new_images=outcome["dom"].get("images") or []
                            best["dom"]["images"]=list({i["src"]:i for i in original_images+new_images}.values())
                    images_good=[x for x in best.get("dom",{}).get("images",[])
                          if "/get-zen_doc/" in x.get("src","") and ("pub_"+item["dzen_id"]+"_") in x["src"]]
                    print("Attempt",n+1,slug,"body",len(best.get("dom",{}).get("main") or ""),
                          "matching images",len(images_good),flush=True)
                    if images_good and best.get("dom",{}).get("main"):break
                except Exception as e:
                    print("Retry failed:",type(e).__name__,str(e)[:140],flush=True)
                finally:
                    await page.close()
            initial[slug]=best
        await browser.close()
    data["results"]=[initial[x["slug"]] for x in data["results"]]
    probe_file.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Updated read-only browser evidence for",len(missing),"source pages",flush=True)

if __name__=="__main__":asyncio.run(main())
