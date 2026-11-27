"""A curated first-party special project, separate from rubrics and publication."""
import json
import re
from pathlib import Path
from html import escape
from scripts.site_rubrics import publication_label

PATH = "data/dossier.json"
START = "<!-- HPII_DOSSIER_START -->"
END = "<!-- HPII_DOSSIER_END -->"
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
COVER = re.compile(r"assets/[a-z0-9][a-z0-9/_-]*\.(?:webp|png|jpg|jpeg)\Z")
DESCRIPTION = "Авторские расследования, большие разборы и исследования ХПИИ."

def load_ids(root):
    path = Path(root)/PATH
    if not path.is_file():
        return []
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cfg,dict) or set(cfg)!={"schema_version","items"} or cfg["schema_version"]!=1:
        raise ValueError("Invalid Dossier config")
    ids = cfg["items"]
    if not isinstance(ids,list) or len(ids)>500 or any(
        not isinstance(x,str) or len(x)>72 or not ID.fullmatch(x) for x in ids
    ) or len(set(ids))!=len(ids):
        raise ValueError("Invalid Dossier member IDs")
    return ids

def rows_for(records, ids):
    by_id = {r["id"]:r for r in records}
    rows=[]
    for sid in ids:
        row=by_id.get(sid)
        if not row or row.get("url")!="articles/"+sid+"/" or not COVER.fullmatch(row.get("cover","")):
            raise ValueError("Dossier accepts only published article IDs: "+sid)
        rows.append(row)
    return rows

def card(row,prefix=""):
    return ('<a class="dossier-card" href="'+escape(prefix+row["url"],quote=True)+'">'
            '<span class="dossier-card-art"><img loading="lazy" src="'+escape(prefix+row["cover"],quote=True)
            +'" alt="Обложка: '+escape(row["title"],quote=True)+'"></span>'
            '<span class="dossier-card-copy"><small class="dossier-label">ДОСЬЕ / ХПИИ</small><strong>'
            +escape(row["title"])+'</strong><span class="dossier-date">'+escape(publication_label(row))
            +'</span><span class="dossier-summary">'+escape(row["summary"])
            +'</span><span class="dossier-read">Читать материал ↗</span></span></a>')

HOME_LIMIT = 6


def home_section(records,ids):
    rows=rows_for(records,ids)
    if not rows:
        return ""
    visible=rows[:HOME_LIMIT]
    slides="\n".join(
        '<div class="dossier-slide" id="dossier-slide-'+str(i)+'">'+card(row)+'</div>'
        for i,row in enumerate(visible,1))
    navigation=""
    if len(visible)>1:
        thumbs="\n".join(
            '<a class="dossier-thumb" href="#dossier-slide-'+str(i)+'" data-dossier-index="'+str(i-1)+
            '" aria-label="Показать: '+escape(row["title"],quote=True)+'">'+
            '<img loading="lazy" src="'+escape(row["cover"],quote=True)+'" alt="Обложка: '+escape(row["title"],quote=True)+'">'+
            '<span>'+escape(row["title"])+'</span></a>'
            for i,row in enumerate(visible,1))
        navigation=(
            '<div class="dossier-nav"><div class="dossier-thumbs" aria-label="Материалы Досье">'+thumbs+
            '</div><div class="dossier-controls" hidden>'+
            '<button type="button" data-dossier-prev aria-label="Предыдущий материал">←</button>'+
            '<span class="dossier-count" aria-live="polite">1 / '+str(len(visible))+'</span>'+
            '<button type="button" data-dossier-next aria-label="Следующий материал">→</button></div></div>'+
            '<script defer src="assets/dossier-showcase.js"></script>')
    return ('  <section class="wrap dossier-home" id="dossier" aria-labelledby="dossier-heading">\n'
            '    <div class="dossier-head"><div><span class="dossier-label">ХПИИ / СПЕЦПРОЕКТ</span>'
            '<h2 id="dossier-heading">Досье</h2><p>'+DESCRIPTION+'</p></div>'
            '<a href="dossier/">Все материалы ↗</a></div>\n'
            '    <div class="dossier-showcase" tabindex="0" aria-label="Витрина Досье">'+slides+'</div>\n'
            +navigation+'\n  </section>')


def update_home_dossier(html,records,root):
    # Older fixtures and uninstalled deployments have no special-project slot.
    if START not in html and END not in html:
        if (Path(root)/PATH).is_file():
            raise ValueError("Dossier homepage slot missing")
        return html
    if html.count(START)!=1 or html.count(END)!=1:
        raise ValueError("Duplicate Dossier homepage markers")
    before,rest=html.split(START,1)
    _,after=rest.split(END,1)
    return before+START+"\n"+home_section(records,load_ids(root))+"\n"+END+after

def article_marker(sid,ids):
    if sid not in ids:
        return ""
    return '<a class="dossier-article-marker" href="../../dossier/">ХПИИ / ДОСЬЕ <span>Спецпроект ↗</span></a>\n'

def mark_article(page,sid,ids):
    # Only this owned decoration changes; the cover bytes and body do not.
    old=re.compile(r'<a class="dossier-article-marker" href="../../dossier/">ХПИИ / ДОСЬЕ <span>Спецпроект ↗</span></a>\n')
    clean=old.sub("",page)
    boundary='<p class="kicker">'
    if sid not in ids:
        return clean
    if clean.count(boundary)!=1:
        raise ValueError("Dossier article header is ambiguous: "+sid)
    return clean.replace(boundary,article_marker(sid,ids)+boundary,1)

def archive(records,ids):
    rows=rows_for(records,ids)
    cards="\n".join(card(r,"../") for r in rows)
    if not cards:
        cards='<p>Пока нет опубликованных материалов спецпроекта.</p>'
    return '''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Досье — ХПИИ</title><meta name="description" content="Авторские расследования, большие разборы и исследования ХПИИ.">
<link rel="canonical" href="https://iipike.ru/dossier/"><link rel="stylesheet" href="../assets/site.css">
<link rel="icon" href="../assets/icon.svg" type="image/svg+xml"></head>
<body><header class="header"><div class="wrap bar"><a class="logo" href="../"><span class="badge">ХПИ</span><span>ХРОНИКИ<br>ПИКИРУЮЩЕГО ИИ<small>НОВОСТИ БЕЗ ИСТЕРИКИ</small></span></a>
<nav class="menu"><a href="../">Главная</a><a href="../articles/">Все статьи</a></nav></div></header>
<main class="wrap dossier-archive"><a href="../">← Главная</a>
<div class="dossier-head"><div><span class="dossier-label">ХПИИ / СПЕЦПРОЕКТ</span><h1>Досье</h1><p>'''+DESCRIPTION+'''</p></div></div>
<div class="dossier-grid" data-count="'''+str(len(rows))+'''">'''+cards+'''</div></main>
<footer class="footer"><div class="wrap"><strong>Хроники Пикирующего ИИ</strong><p>Проверяем факты и указываем первоисточники.</p></div></footer>
<script defer src="../assets/social-footer.js"></script></body></html>
'''
