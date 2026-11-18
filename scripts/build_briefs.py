#!/usr/bin/env python3
"""Render approved HPII briefs separately from long-form news and its hourly queue.

The candidate list is NEVER read by this publisher. A human-approved record in
data/briefs/approved.json is the only possible public input. No images required.
"""
import argparse
from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
APPROVED=Path("data/briefs/approved.json")
CANDIDATES=Path("data/briefs/candidates.json")
SITE=Path("briefs/index.html")
HOME=Path("index.html")
BEGIN="<!-- HPII_BRIEFS_ITEMS_START -->"
END="<!-- HPII_BRIEFS_ITEMS_END -->"
HBEGIN="<!-- HPII_BRIEFS_HOME_START -->"
HEND="<!-- HPII_BRIEFS_HOME_END -->"
ID=re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
POOL_ID=re.compile(r"n-[0-9a-f]{16}\Z")
ISSUE=re.compile(r"https://github\.com/AfterDark1000/iipike-site/issues/[1-9]\d*\Z")
BASE="https://iipike.ru"

def safe_https(raw):
    if not isinstance(raw,str) or len(raw)>2048:
        raise ValueError("Invalid source URL")
    p=urlparse(raw)
    if p.scheme!="https" or not p.hostname or p.username or p.password or p.fragment:
        raise ValueError("Source must be absolute trusted HTTPS")
    if p.hostname in ("localhost","127.0.0.1") or p.hostname.endswith(".local"):
        raise ValueError("Local source URL forbidden")
    return raw

def parse_time(raw):
    if not isinstance(raw,str) or not raw.endswith("Z"):
        raise ValueError("UTC ISO date required")
    d=datetime.fromisoformat(raw.replace("Z","+00:00"))
    if d.utcoffset().total_seconds()!=0:
        raise ValueError("Time must be UTC")
    return d

def read_candidates(root):
    path=root/CANDIDATES
    source=json.loads(path.read_text(encoding="utf-8"))
    if source.get("schema_version")!=1 or not isinstance(source.get("items"),list):
        raise ValueError("Invalid candidate file")
    ids=set()
    for c in source["items"]:
        if c.get("status")!="pending_review" or not ID.fullmatch(str(c.get("slug",""))):
            raise ValueError("Candidate is not pending review")
        if c["slug"] in ids:raise ValueError("Duplicate candidate")
        ids.add(c["slug"])
        if not POOL_ID.fullmatch(c.get("pool_id","")):raise ValueError("Invalid candidate pool ID")
        safe_https(c.get("source_url"))
        if not c.get("headline") or not c.get("body") or not c.get("fact_check"):
            raise ValueError("Unresearched candidate")
    return source["items"]

def validated(root):
    doc=json.loads((root/APPROVED).read_text(encoding="utf-8"))
    if doc.get("schema_version")!=1 or not isinstance(doc.get("items"),list):
        raise ValueError("Invalid approved briefs registry")
    candidates={c["slug"]:c for c in read_candidates(root)}
    published=json.loads((root/"news.json").read_text(encoding="utf-8"))
    prior_sources={v.get("source_url") for v in published}
    seen_ids=set();seen_pool=set();seen_sources=set();out=[]
    required={"slug","pool_id","pool_sequence","headline","topic","event_date","source","source_url",
              "body","status","approved_by","approval_ref","approved_at_utc","published_at_utc"}
    for row in doc["items"]:
        if not isinstance(row,dict) or set(row)!=required:raise ValueError("Approved brief fields invalid")
        slug=row["slug"]
        if not isinstance(slug,str) or len(slug)>80 or not ID.fullmatch(slug) or slug in seen_ids:
            raise ValueError("Duplicate/unsafe brief slug")
        if row["pool_id"] in seen_pool or not POOL_ID.fullmatch(row["pool_id"]):
            raise ValueError("Duplicate/unsafe pool ID")
        source=safe_https(row["source_url"])
        if source in prior_sources or source in seen_sources:
            raise ValueError("Duplicate source against long articles/briefs")
        if row["status"]!="editor_approved" or row["approved_by"]!="human_editor" or not ISSUE.fullmatch(str(row["approval_ref"])):
            raise ValueError("Missing explicit human editorial approval")
        cand=candidates.get(slug)
        if not cand or any(row[k]!=cand[k] for k in ("pool_id","pool_sequence","headline","topic","event_date","source","source_url","body")):
            raise ValueError("Published text must exactly match its reviewed candidate")
        if row["topic"] not in ("Наука","Бизнес","Общество","Технологии","Культура","Безопасность"):
            raise ValueError("Invalid brief topic")
        if not isinstance(row["headline"],str) or not 15<=len(row["headline"])<=120:
            raise ValueError("Bad headline")
        if not isinstance(row["body"],str) or not 280<=len(row["body"])<=900 or "\n" in row["body"]:
            raise ValueError("A short brief must be 280-900 characters in one paragraph")
        if row["event_date"]!=cand["event_date"] or not re.fullmatch(r"20\d\d-\d\d-\d\d",row["event_date"]):
            raise ValueError("Invalid event date")
        if not isinstance(row["pool_sequence"],int) or row["pool_sequence"]<1:
            raise ValueError("Invalid original pool sequence")
        approved_at=parse_time(row["approved_at_utc"])
        published_at=parse_time(row["published_at_utc"])
        if published_at<approved_at:raise ValueError("Publishing before approval")
        seen_ids.add(slug);seen_pool.add(row["pool_id"]);seen_sources.add(source);out.append(row)
    return sorted(out,key=lambda x:(x["published_at_utc"],x["slug"]),reverse=True)

def swap(text,start,end,content):
    if text.count(start)!=1 or text.count(end)!=1 or text.index(start)>text.index(end):
        raise ValueError("Missing/duplicate protected HTML markers")
    a=text.index(start)+len(start); b=text.index(end)
    return text[:a]+"\n"+content+"\n"+text[b:]

def date_label(iso):
    d=datetime.fromisoformat(iso.replace("Z","+00:00"))
    months=("января","февраля","марта","апреля","мая","июня","июля","августа",
            "сентября","октября","ноября","декабря")
    return f"{d.day} {months[d.month-1]} {d.year}"

def card(r):
    slug=r["slug"]
    return ('<article class="brief-item" id="'+escape(slug)+'">'
            '<div class="brief-meta"><time datetime="'+escape(r["published_at_utc"])+'">'+
            date_label(r["published_at_utc"])+'</time><span>'+escape(r["topic"])+'</span></div>'
            '<h2><a href="'+escape(slug)+'/">'+escape(r["headline"])+'</a></h2>'
            '<p>'+escape(r["body"])+'</p><div class="brief-links">'
            '<a href="'+escape(slug)+'/">Постоянная ссылка ↗</a>'
            '<a href="'+escape(r["source_url"],quote=True)+'" target="_blank" rel="noopener noreferrer">'
            'Первоисточник: '+escape(r["source"])+' ↗</a></div></article>')

def home_strip(rows):
    if not rows:
        return ('<div class="brief-home-empty">Небольшие истории без длинных статей и обложек. '
                'Первая подборка на редакционной проверке.</div>')
    return "\n".join('<a class="brief-home-link" href="briefs/'+escape(r["slug"])+'/">'
                     '<span>'+escape(r["topic"])+'</span><strong>'+
                     escape(r["headline"])+'</strong><span aria-hidden="true">↗</span></a>'
                     for r in rows[:3])

def render_page(r):
    head=escape(r["headline"]);body=escape(r["body"]);canonical=BASE+"/briefs/"+r["slug"]+"/"
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{escape(r["body"][:155],quote=True)}">
<link rel="canonical" href="{canonical}"><meta property="og:type" content="article">
<meta property="og:title" content="{escape(head,quote=True)}">
<meta property="og:url" content="{canonical}">
<link rel="stylesheet" href="../../assets/site.css"><link rel="stylesheet" href="../../assets/briefs.css">
<title>{head} — Новости коротко — ХПИИ</title></head>
<body class="brief-page"><header class="header"><div class="wrap bar"><a class="logo" href="../../"><span class="badge">ХПИ</span><span>ХРОНИКИ<br>ПИКИРУЮЩЕГО ИИ<small>НОВОСТИ БЕЗ ИСТЕРИКИ</small></span></a><nav class="menu"><a href="../../">Главная</a><a href="../">Новости коротко</a><a href="../../articles/">Статьи</a></nav></div></header>
<main class="wrap brief-article"><p class="brief-kicker"><a href="../">← Новости коротко</a> / {escape(r["topic"])}</p>
<h1>{head}</h1><p class="brief-date"><time datetime="{escape(r["published_at_utc"])}">{date_label(r["published_at_utc"])}</time></p>
<p class="brief-full-text">{body}</p>
<p class="brief-source">Первоисточник: <a href="{escape(r["source_url"],quote=True)}" rel="noopener noreferrer" target="_blank">{escape(r["source"])} ↗</a></p>
<p class="brief-return"><a href="../">Ещё короткие новости →</a></p>
</main><footer class="footer"><div class="wrap">Хроники Пикирующего ИИ · <a href="../">Новости коротко</a></div></footer>
<script defer src="../../assets/social-footer.js"></script></body></html>
'''

def feed(rows):
    entries=[]
    for r in rows[:50]:
        url=BASE+"/briefs/"+r["slug"]+"/"
        entries.append('<item><title>'+escape(r["headline"])+'</title><link>'+url+
          '</link><guid isPermaLink="true">'+url+'</guid><description>'+escape(r["body"])+
          '</description><pubDate>'+datetime.fromisoformat(r["published_at_utc"].replace("Z","+00:00")).strftime("%a, %d %b %Y %H:%M:%S +0000")+
          '</pubDate></item>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>ХПИИ — Новости коротко</title>'
            '<link>'+BASE+'/briefs/</link><description>Короткие новости ИИ без картинок</description>'+
            ''.join(entries)+'</channel></rss>\n')

def sitemap(rows):
    entries=[BASE+"/briefs/"]+[BASE+"/briefs/"+r["slug"]+"/" for r in rows]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'+
            ''.join('  <url><loc>'+escape(u)+'</loc></url>\n' for u in entries)+'</urlset>\n')

def outputs(root):
    rows=validated(root)
    index=(root/SITE).read_text(encoding="utf-8")
    home=(root/HOME).read_text(encoding="utf-8")
    item_html="\n".join(map(card,rows)) if rows else (
      '<p class="brief-empty">Пока короткие новости готовятся к редакционному утверждению. '
      'Здесь будут только проверенные и одобренные заметки.</p>')
    output={
      root/SITE:swap(index,BEGIN,END,item_html),
      root/HOME:swap(home,HBEGIN,HEND,home_strip(rows)),
      root/"briefs/feed.xml":feed(rows),
      root/"briefs/sitemap.xml":sitemap(rows)
    }
    for r in rows:output[root/"briefs"/r["slug"]/"index.html"]=render_page(r)
    return output

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--write",action="store_true")
    p.add_argument("--check",action="store_true")
    args=p.parse_args()
    if args.write and args.check:p.error("Choose only one mode")
    result=outputs(ROOT)
    changes=[path for path,val in result.items()
             if not path.exists() or path.read_text(encoding="utf-8")!=val]
    if args.check and changes:
        p.error("Brief pages need rebuilding: "+", ".join(str(x.relative_to(ROOT)) for x in changes))
    if args.write:
        for path in changes:
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(result[path],encoding="utf-8")
    print(f"Approved short news: {len(result)-4}; changed files: {len(changes)}; write={args.write}")

if __name__=="__main__":
    main()
