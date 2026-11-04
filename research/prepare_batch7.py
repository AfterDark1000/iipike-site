#!/usr/bin/env python3
"""Rebuild sixth-month HPII history from authenticated Dzen date-only originals.

Every selected item has: HTTP 200 at canonical Dzen URL; OG title and article ID
observed on that page; Dzen's actual datePublished calendar day; complete original
body boundaries; genuine user-owned cover image. No invented UTC time.
All 40 titles/URLs/days are independently verified; select up to 30 complete art.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
from scripts.site_related import suggest, catalog_entries, verified

ROOT=Path(__file__).resolve().parents[1]
INPUT=ROOT/"research/batch7_candidates.json"
EVIDENCE=ROOT/"research/batch7_date_title_evidence.json"
PROBES=ROOT/"research/batch7_probe_results.json"
COVERS=ROOT/"research/batch7_cover_report.json"
SNAPSHOT=ROOT/"data/editorial_full_catalog_snapshot.json"
DEST=ROOT/"content/approved"
REPORT=ROOT/"research/batch7_preparation_report.json"

ru="абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
trans=("a,b,v,g,d,e,yo,zh,z,i,y,k,l,m,n,o,p,r,s,t,u,f,kh,ts,ch,sh,sch,,y,,e,yu,ya").split(",")
MAPPING=dict(zip(ru,trans))
def slugify(title,dzen_id):
    raw="".join(MAPPING.get(c,c) for c in title.lower())
    slug=re.sub("[^a-z0-9]+","-",raw).strip("-")[:62].rstrip("-")
    if not slug:raise ValueError("Unable to construct original title slug")
    return slug+"-"+dzen_id[-5:]

def category(title):
    if re.search(r"взлом|хакер|парол|утечк|обход|арест|уязв|системы индийских|криптокошел|опасного поведения|проник|доступ к данным|защит[уы]",title,re.I):
        return "skynet"
    if re.search(r"самого себя|учится размножаться|водить машину|тысяч ии-агентов",title,re.I):
        return "what-are-you-doing"
    if re.search(r"глав[аы] мвф|трамп|предупредил|объявила дату",title,re.I):
        return "quotes"
    return "news"

def main():
    batch=json.loads(INPUT.read_text(encoding="utf-8"))["candidates"]
    source={r["slug"]:r for r in json.loads(PROBES.read_text(encoding="utf-8"))["results"]}
    evidence={r["slug"]:r for r in json.loads(EVIDENCE.read_text(encoding="utf-8"))["records"]}
    covers={r["slug"]:r for r in json.loads(COVERS.read_text(encoding="utf-8"))["entries"]}
    snapshot=json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    catalog={r["dzen_id"]:r for r in snapshot["entries"]}
    prior=json.loads((ROOT/"news.json").read_text(encoding="utf-8"))
    prior_ids={x.get("dzen_id") for x in prior}
    prior_slugs={x["id"] for x in prior}
    if len(batch)!=len(source) or len(source)!=len(evidence) or len(evidence)!=len(covers) or len(batch)!=40:
        raise ValueError("40-source audit evidence missing or duplicated")

    verified_rows=[]
    for item in batch:
        slug=item["slug"];ident=item["dzen_id"];ev=evidence[slug];p=source[slug]
        original=catalog.get(ident)
        dom=p.get("dom") or {}
        date=ev.get("source_date")
        title=ev.get("source_og_title")
        dates=[x.get("value") for x in dom.get("date_meta",[]) if x.get("key")=="datePublished"]
        if (not original or ident in prior_ids or not ev.get("original_page_verified")
                or p.get("http_status")!=200 or p.get("final_url")!=item["dzen_url"]
                or "/pub_"+ident+"_" not in (dom.get("og_image") or "")
                or dates!=[date] or not re.fullmatch(r"2026-\d{2}-\d{2}",date or "")
                or not title or title!=dom.get("og_title")):
            raise ValueError("Incorrect original Dzen identity/date/title: "+slug)
        dt.date.fromisoformat(date)
        # Preserve the original logged metadata for audit, and promote only
        # values independently seen on the corresponding public Dzen page.
        if original.get("title")!=title:
            original["previous_workflow_title"]=original.get("title")
        original["title"]=title
        original["title_evidence"]="verified_on_public_dzen_page"
        original["url_evidence"]="verified_on_public_dzen_page"
        original["published_date"]=date
        original["published_date_evidence"]="dzen_itemprop_datePublished"
        original["source"]="original_public_dzen_article"
        original["published_at_utc"]=None if "published_at_utc" in original else original.get("published_at_utc")
        original.pop("published_at_utc",None)
        first=ev.get("first_excerpt_at");end=ev.get("text_footer_at")
        main_text=dom.get("main") or ""
        if not isinstance(first,int) or not isinstance(end,int) or first<0 or end<=first:
            raise ValueError("Cannot locate original article body bounds: "+slug)
        body=main_text[first:end].strip()
        if len(body)<500:
            raise ValueError("Original text below safe 500-char threshold: "+slug)
        blocks=[x.strip() for x in body.split("\n\n") if x.strip()]
        if not 2<=len(blocks)<=70 or any("Подпишитесь на канал" in x for x in blocks):
            raise ValueError("Original paragraph validation failed: "+slug)
        original["excerpt"]=re.sub(r"\s+"," ",blocks[0]).strip()[:420]
        verified_rows.append((item,ev,body,blocks))

    snapshot["entries"]=list(catalog.values())
    SNAPSHOT.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    verified_catalog=catalog_entries(ROOT)
    if not all(verified(verified_catalog[r["dzen_id"]]) for r in batch):
        raise ValueError("Promoted catalog entries did not pass site provenance gates")

    valid=[]
    for item,ev,body,blocks in verified_rows:
        art=covers[item["slug"]]
        if art.get("status")!="downloaded":continue
        if art.get("source") not in ("telegram_original_photo","dzen_article_image",
                                     "dzen_article_original_native_crop"):continue
        w=art.get("width",0);h=art.get("height",0)
        if w<780 or h<430 or not 1.65<w/h<1.86:continue
        if "get-zen-pub-og" in art.get("source_url",""):continue
        if not (ROOT/art["cover"]).is_file():continue
        valid.append((item,ev,body,blocks,art))
    if len(valid)<30:
        raise ValueError(f"Only {len(valid)} original artworks available, require thirty")

    selected=valid[:30]
    output=[];report=[];new_slugs=set()
    public_ids={x["dzen_id"] for x in prior if x.get("dzen_id")}
    selection_ids={x[0]["dzen_id"] for x in selected}
    for item,ev,body,blocks,art in selected:
        title=ev["source_og_title"]
        dzen_id=item["dzen_id"]
        slug=slugify(title,dzen_id)
        if slug in prior_slugs or slug in new_slugs:
            raise ValueError("New article slug duplicates an existing address: "+slug)
        new_slugs.add(slug)
        old_image=ROOT/art["cover"]
        filename="assets/imported/"+slug+".webp"
        new_image=ROOT/filename
        new_image.parent.mkdir(parents=True,exist_ok=True)
        if old_image!=new_image:
            if new_image.exists():raise ValueError("Do not replace previous art: "+filename)
            new_image.write_bytes(old_image.read_bytes())
        image_sha=hashlib.sha256(new_image.read_bytes()).hexdigest()
        if image_sha!=art["sha256"]:raise ValueError("Original artwork hash mismatch: "+slug)
        headings={x.get("text") for x in (source[item["slug"]].get("dom") or {}).get("headings",[])
                  if x.get("tag") in ("H2","H3")}
        paragraph_data=[{"type":"lead" if i==0 else "h2" if part in headings else "p","text":part}
                        for i,part in enumerate(blocks)]
        excerpt=re.sub(r"\s+"," ",blocks[0]).strip()
        summary=excerpt[:275].rsplit(" ",1)[0].rstrip(" ,;:")
        if len(summary)<50:
            summary=re.sub(r"\s+"," ",body[:275]).strip().rsplit(" ",1)[0]
        if len(summary)<50:raise ValueError("Original summary is too short: "+slug)
        date=ev["source_date"]
        category_name=category(title)
        matches=suggest({"title":title,"summary":summary,"dzen_id":dzen_id},verified_catalog,limit=20)
        related=[]
        for hit_count,match_title,ref in matches:
            if hit_count<2 or ref==dzen_id or ref in related:continue
            if ref in public_ids or ref in selection_ids:
                related.append(ref)
            if len(related)>=2:break
        record={
            "slug":slug,"status":"approved","approved_by":"Редакция ХПИИ — перенос авторского архива",
            "approved_at":"2026-11-04","title":title,"summary":summary,"published":date,
            "publication_date_precision":"day","rubric":category_name,
            "section":"ИСТОРИЧЕСКИЙ АРХИВ","source_url":item["dzen_url"],
            "source_title":"ХПИИ — исходная публикация в Дзене","cover":filename,
            "dzen_id":dzen_id,"dzen_url":item["dzen_url"],"related_dzen_ids":related,
            "paragraphs":paragraph_data
        }
        target=DEST/(slug+".json")
        if target.exists():raise ValueError("Attempt to overwrite approved source: "+slug)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        output.append({
            "slug":slug,"dzen_id":dzen_id,"title":title,
            "prior_log_title":item["title"],"dzen_url":item["dzen_url"],
            "published":date,"original_date_evidence":"Dzen itemprop=datePublished",
            "publication_date_precision":"day","source_full_text_characters":len(body),
            "cover":filename,"cover_source":art["source"],
            "image_url_source":art["source_url"],
            "source_telegram_post":("https://t.me/"+art["telegram_post"]
                                    if art.get("telegram_post") else None),
            "artwork_width":art["width"],"artwork_height":art["height"],"sha256":image_sha,
            "related_source_ids":related,"rubric":category_name
        })
        report.append({"slug":slug,"status":"ready","body_chars":len(body),
                       "paragraphs":len(blocks),"cover":filename,"date":date})
    (ROOT/"registry").mkdir(exist_ok=True)
    (ROOT/"registry/archive_batch7_sources.json").write_text(json.dumps({
        "schema_version":1,"batch":7,
        "policy":"Original Dzen day-only date; no forged publication time, exact title and own art",
        "selected_count":len(output),"verified_historical_pages":len(verified_rows),
        "entries":output
    },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    REPORT.write_text(json.dumps({"batch":7,"ready":len(report),"not_ready":0,
        "eligible_high_res_art":len(valid),"entries":report},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("PROMOTED EXACT SOURCE PAGE RECORDS",len(verified_rows),flush=True)
    print("SELECTED FULL ORIGINALS",len(output),"WITH GENUINE 16:9 COVERS",flush=True)
    for x in output:
        print("READY",x["slug"],x["published"],"cover",x["artwork_width"],x["artwork_height"],flush=True)

if __name__=="__main__":
    main()
