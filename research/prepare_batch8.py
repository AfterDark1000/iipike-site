#!/usr/bin/env python3
"""Finish HPII's 218-entry legacy Dzen catalog with 28 authenticated originals.

Each article must have the same Dzen ID, original title, author's public page,
full captured original body, exact source calendar day (and UTC timestamp where
the historical archive recorded it) and original artwork. Never guess anything.
"""
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.site_related import catalog_entries, suggest, verified

HERE=ROOT/"research"
manifest=json.loads((HERE/"batch8_candidates.json").read_text(encoding="utf-8"))["candidates"]
source={x["slug"]:x for x in json.loads((HERE/"batch8_probe_results.json").read_text(encoding="utf-8"))["results"]}
evidence={x["research_slug"]:x for x in json.loads((HERE/"batch8_source_audit.json").read_text(encoding="utf-8"))["records"]}
images={x["slug"]:x for x in json.loads((HERE/"batch8_cover_report.json").read_text(encoding="utf-8"))["entries"]}
snapshot_path=ROOT/"data/editorial_full_catalog_snapshot.json"
snapshot=json.loads(snapshot_path.read_text(encoding="utf-8"))
original_catalog={x["dzen_id"]:x for x in snapshot["entries"]}
old_news=json.loads((ROOT/"news.json").read_text(encoding="utf-8"))
old_ids={x["dzen_id"] for x in old_news if x.get("dzen_id")}
old_slugs={x["id"] for x in old_news}
assert len(manifest)==len(source)==len(evidence)==len(images)==28
assert len(snapshot["entries"])==218 and len(old_news)==191 and len(old_ids)==190
ru="абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
trans="a,b,v,g,d,e,yo,zh,z,i,y,k,l,m,n,o,p,r,s,t,u,f,kh,ts,ch,sh,sch,,y,,e,yu,ya".split(",")
T=dict(zip(ru,trans))
def slugify(title,ident):
    txt="".join(T.get(c,c) for c in title.lower())
    name=re.sub(r"[^a-z0-9]+","-",txt).strip("-")[:62].rstrip("-")
    if not name:raise ValueError("Empty article slug for original title")
    return name+"-"+ident[-5:]
def rubric(title,kind):
    if kind=="daily_digest":return "news"
    if re.search(r"взлом|хакер|парол|утечк|обход|арест|уязв|донос|полици|визы|банк|сбо[йи]|защит[уы]|данным|киберспец",title,re.I):
        return "skynet"
    if re.search(r"самого себя|размножаться|водить машину|ложный сигнал|20 заявлений|не просил",title,re.I):
        return "what-are-you-doing"
    if re.search(r"предупредил|маск|трамп|глава мвф",title,re.I):
        return "quotes"
    return "news"

known_day_only=0
historical_with_time=0
verified_text=[]
for old in manifest:
    ident=old["dzen_id"]
    if ident in old_ids:raise ValueError("Already published in main catalog: "+ident)
    doc=source[old["slug"]]
    ev=evidence[old["slug"]]
    src=original_catalog[ident]
    dom=doc.get("dom") or {}
    actual_title=(dom.get("og_title") or "").strip()
    original_day=ev.get("day")
    date_meta=[x.get("value") for x in dom.get("date_meta",[]) if x.get("key")=="datePublished"]
    if (not ev.get("valid_source") or doc.get("http_status")!=200
        or doc.get("final_url")!=old["dzen_url"]
        or "/pub_"+ident+"_" not in (dom.get("og_image") or "")
        or "Хроники Пикирующего ИИ" not in (dom.get("main") or "")[:1400]
        or not actual_title or actual_title!=ev["title"]
        or date_meta!=[original_day]
        or src.get("dzen_url")!=old["dzen_url"]):
        raise ValueError("Cannot verify exact original article identity: "+ident)
    dt.date.fromisoformat(original_day)
    exact=src.get("published_at_utc")
    if exact:
        published=dt.datetime.fromisoformat(exact.replace("Z","+00:00"))
        if published.tzinfo is None:raise ValueError("Original timestamp must be timezone-aware")
        if published.astimezone(ZoneInfo("Asia/Yekaterinburg")).date().isoformat()!=original_day:
            raise ValueError("Original exact time contradicts Dzen page date: "+ident)
        published_utc=published.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        historical_with_time+=1
    else:
        published_utc=None
        known_day_only+=1
    if src.get("title") and src["title"]!=actual_title:
        raise ValueError("Unexpected original title mismatch: "+ident)
    if not src.get("title"):src["previous_workflow_title"]=None
    src.update({"title":actual_title,
        "title_evidence":"verified_on_public_dzen_page",
        "url_evidence":"verified_on_public_dzen_page",
        "source":"original_public_dzen_article",
        "published_date":original_day,
        "published_date_evidence":"dzen_itemprop_datePublished",
        })
    a=ev["original_body_start"];b=ev["original_body_end"]
    main=dom.get("main") or ""
    if not isinstance(a,int) or not isinstance(b,int) or not (0<=a<b<=len(main)):
        raise ValueError("Original article body boundaries are unverified: "+ident)
    body=main[a:b].strip()
    minimum=380 if ident=="6acc57b80e28a620956e111e" else 500
    if len(body)<minimum:
        raise ValueError("Original text too short for complete import: "+ident)
    blocks=[x.strip() for x in body.split("\n\n") if x.strip()]
    if len(blocks)<2 or len(blocks)>90 or any("Подпишитесь на канал" in x for x in blocks):
        raise ValueError("Article end marker appears inside source paragraphs: "+ident)
    src["excerpt"]=re.sub(r"\s+"," ",blocks[0]).strip()[:420]
    art=images[old["slug"]]
    if (art.get("status")!="downloaded" or
        art.get("source") not in ("telegram_original_photo","dzen_article_image","dzen_article_original_native_crop")
        or "get-zen-pub-og" in art.get("source_url","")
        or art.get("width",0)<780 or art.get("height",0)<430
        or not 1.65<art["width"]/art["height"]<1.86):
        raise ValueError("Original artwork absent, wrong format or branded: "+ident)
    if art["source"]=="telegram_original_photo" and not str(art.get("telegram_post") or "").startswith("iipike/"):
        raise ValueError("Telegram image source post not verified: "+ident)
    if art["source"]=="dzen_article_original_native_crop" and (
       "/pub_"+ident+"_" not in art["source_url"] or
       art.get("crop_comparison_mean_rgb_error",100)>35):
        raise ValueError("Dzen native image crop not independently verified: "+ident)
    img=ROOT/art["cover"]
    if not img.is_file() or img.stat().st_size<15000 or hashlib.sha256(img.read_bytes()).hexdigest()!=art["sha256"]:
        raise ValueError("Original image bytes or SHA mismatch: "+ident)
    verified_text.append((old,src,dom,body,blocks,art,published_utc))

snapshot_path.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
catalog=catalog_entries(ROOT)
assert all(verified(catalog[x["dzen_id"]]) for x in manifest)
source_ids={x["dzen_id"] for x in manifest}
assert len(source_ids)==28 and not source_ids.intersection(old_ids)
entries=[]
pending_slugs=set()
outdir=ROOT/"content/approved"
outdir.mkdir(parents=True,exist_ok=True)
for old,src,dom,body,blocks,art,published_utc in verified_text:
    ident=old["dzen_id"]
    title=src["title"]
    slug=slugify(title,ident)
    if slug in old_slugs or slug in pending_slugs:raise ValueError("Duplicate article slug: "+slug)
    pending_slugs.add(slug)
    source_img=ROOT/art["cover"]
    dest_rel="assets/imported/"+slug+".webp"
    image=ROOT/dest_rel
    image.parent.mkdir(parents=True,exist_ok=True)
    if source_img!=image:
        if image.exists():raise ValueError("Do not overwrite another article cover: "+dest_rel)
        image.write_bytes(source_img.read_bytes())
    actual_hash=hashlib.sha256(image.read_bytes()).hexdigest()
    assert actual_hash==art["sha256"]
    summary=re.sub(r"\s+"," ",blocks[0]).strip()
    if len(summary)>275:summary=summary[:275].rsplit(" ",1)[0].rstrip(" ,;:")
    if len(summary)<50:summary=re.sub(r"\s+"," ",body[:275]).strip().rsplit(" ",1)[0]
    if len(summary)<40:raise ValueError("Original summary insufficient: "+slug)
    headings={h.get("text") for h in dom.get("headings",[]) if h.get("tag") in ("H2","H3")}
    paragraphs=[{"type":"lead" if i==0 else ("h2" if part in headings else "p"),"text":part}
                for i,part in enumerate(blocks)]
    date=src["published_date"]
    refs=[]
    hits=suggest({"title":title,"summary":summary,"dzen_id":ident},catalog,limit=30)
    for overlap,other_title,ref in hits:
        if overlap<2 or ref==ident or ref in refs:continue
        if ref in source_ids or ref in old_ids:refs.append(ref)
        if len(refs)>=2:break
    rec={"slug":slug,"status":"approved","approved_by":"Редакция ХПИИ — перенос авторского исторического архива",
         "approved_at":"2026-11-04","title":title,"summary":summary,"published":date,
         "rubric":rubric(title,old["kind"]),"section":"ИСТОРИЧЕСКИЙ АРХИВ",
         "source_url":old["dzen_url"],"source_title":"ХПИИ — исходная публикация в Дзене",
         "cover":dest_rel,"dzen_id":ident,"dzen_url":old["dzen_url"],"related_dzen_ids":refs,
         "paragraphs":paragraphs}
    if published_utc:
        rec["published_at_utc"]=published_utc
    else:
        rec["publication_date_precision"]="day"
    jsonpath=outdir/(slug+".json")
    if jsonpath.exists():raise ValueError("Approved source already exists: "+slug)
    jsonpath.write_text(json.dumps(rec,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    entries.append({"slug":slug,"dzen_id":ident,"dzen_url":old["dzen_url"],
        "title":title,"kind":old["kind"],"published":date,
        "published_at_utc":published_utc,
        "publication_date_precision":"second" if published_utc else "day",
        "source_full_text_characters":len(body),"paragraph_count":len(blocks),
        "cover":dest_rel,"artwork_width":art["width"],"artwork_height":art["height"],
        "artwork_source_type":art["source"],"artwork_source_url":art["source_url"],
        "telegram_post":("https://t.me/"+art["telegram_post"] if art.get("telegram_post") else None),
        "artwork_sha256":actual_hash,"related_dzen_ids":refs,"rubric":rec["rubric"]})
report={"batch":8,"prepared":len(entries),"remaining":0,
        "day_only":known_day_only,"historical_exact_time":historical_with_time,
        "historical_catalog":len(snapshot["entries"]), "previous_public":len(old_news),
        "entries":entries}
reg=ROOT/"registry/archive_batch8_sources.json"
reg.parent.mkdir(exist_ok=True,parents=True)
reg.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
(HERE/"batch8_preparation_report.json").write_text(json.dumps(
    {"prepared":len(entries),"expected":28,"short_article_exception":"6acc57b80e28a620956e111e",
     "no_unverified_content_included":True,
     "ids":[x["dzen_id"] for x in entries]},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("READY",len(entries),"of 28 originals, exact-time",historical_with_time,
      "calendar-day-only",known_day_only,flush=True)
for entry in entries:print("ARTICLE",entry["slug"],entry["published"],entry["artwork_width"],entry["artwork_height"],flush=True)
