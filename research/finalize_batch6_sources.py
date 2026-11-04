#!/usr/bin/env python3
"""Create durable batch-6 provenance after all original sources pass validation."""
import datetime as dt
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/"research/batch6_candidates.json").read_text(encoding="utf-8"))["candidates"]
covers=json.loads((ROOT/"research/batch6_cover_report.json").read_text(encoding="utf-8"))["entries"]
sources=json.loads((ROOT/"research/batch6_probe_results.json").read_text(encoding="utf-8"))["results"]
prepared=json.loads((ROOT/"research/batch6_preparation_report.json").read_text(encoding="utf-8"))
by_slug={c["slug"]:c for c in covers}
source_by_slug={c["slug"]:c for c in sources}
assert len(manifest)==len(covers)==len(sources)==30
assert prepared["ready"]==30 and prepared["not_ready"]==0
records=[]
for entry in manifest:
    slug=entry["slug"]
    cover=by_slug[slug]
    source=source_by_slug[slug]
    approved=json.loads((ROOT/"content/approved"/(slug+".json")).read_text(encoding="utf-8"))
    if cover.get("status")!="downloaded":
        raise ValueError(f"Missing original cover for {slug}")
    if source.get("http_status")!=200 or (source.get("dom") or {}).get("og_title")!=entry["title"]:
        raise ValueError(f"Original Dzen page not confirmed: {slug}")
    if approved["dzen_id"]!=entry["dzen_id"] or approved["dzen_url"]!=entry["dzen_url"]:
        raise ValueError(f"Article source mismatch: {slug}")
    if approved["published_at_utc"]!=dt.datetime.fromisoformat(
        entry["published_at_utc"].replace("Z","+00:00")
    ).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"):
        raise ValueError(f"Original date overwritten: {slug}")
    img=ROOT/cover["cover"]
    if not img.is_file() or img.stat().st_size<15000:
        raise ValueError(f"Original image not saved: {img}")
    kind=cover.get("source")
    if kind not in ("telegram_original_photo","dzen_article_image"):
        raise ValueError(f"Branded or unverified image forbidden: {slug}")
    if "get-zen-pub-og" in cover.get("source_url",""):
        raise ValueError(f"Branded Dzen social card forbidden: {slug}")
    if not 1.65<cover["width"]/cover["height"]<1.86:
        raise ValueError(f"Not original 16:9 artwork: {slug}")
    if kind=="telegram_original_photo" and not str(cover.get("telegram_post") or "").startswith("iipike/"):
        raise ValueError(f"Telegram post evidence missing: {slug}")
    record={"slug":slug,"dzen_id":entry["dzen_id"],"dzen_url":entry["dzen_url"],
            "published_at_utc":approved["published_at_utc"],"cover":cover["cover"],
            "image_source":kind,"telegram_post":(
                "https://t.me/"+cover["telegram_post"] if cover.get("telegram_post") else None),
            "width":cover["width"],"height":cover["height"],"sha256":cover["sha256"],
            "paragraphs":len(approved["paragraphs"])}
    records.append(record)
out={"schema_version":1,"batch":6,"status":"verified_30_complete_originals",
     "source":"data/editorial_full_catalog_snapshot.json",
     "policy":"Never use Dzen generated OpenGraph share cards; archive exact original text, date and own original artwork",
     "entries":records}
dest=ROOT/"registry/archive_batch6_sources.json"
dest.parent.mkdir(parents=True,exist_ok=True)
dest.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("Verified batch-6 article provenance:",len(records),"/30",flush=True)
