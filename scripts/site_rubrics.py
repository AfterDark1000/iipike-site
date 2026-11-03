"""Canonical HPII rubrics: editorial categories, not extra copies of articles."""
from html import escape
from datetime import date
from pathlib import Path

BASE = "https://iipike.ru"
RUBRICS = {
    "news": {
        "slug": "news", "name": "Новости ИИ",
        "description": "Новые модели, исследования, продукты и события индустрии искусственного интеллекта.",
    },
    "skynet": {
        "slug": "skynet", "name": "Скайнет просыпается",
        "description": "Взломы, сбои и эксперименты с ИИ-агентами, которые повели себя не по плану.",
    },
    "what-are-you-doing": {
        "slug": "what-are-you-doing", "name": "ИИ, ты чего творишь?",
        "description": "Курьёзные, странные и неожиданно забавные истории из мира нейросетей.",
    },
    "quotes": {
        "slug": "quotes", "name": "Громко сказано",
        "description": "Громкие заявления известных людей: кто что сказал и чем слова подтверждаются.",
    },
}


MONTHS_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def publication_date(value):
    """Show an original historical publication day in reader-friendly Russian."""
    day = date.fromisoformat(value)
    return f"{day.day} {MONTHS_RU[day.month - 1]} {day.year}"


def publication_date_caps(value):
    return publication_date(value).upper()


def rubric_link(key, prefix=""):
    if key not in RUBRICS:
        raise ValueError(f"Unknown rubric: {key}")
    return prefix + "rubrics/" + key + "/"


def navigation(prefix=""):
    return "\n".join(
        '<a href="' + rubric_link(k, prefix) + '">' + escape(meta["name"]) + "</a>"
        for k, meta in RUBRICS.items()
    )


def render_page(key, records):
    if key not in RUBRICS:
        raise ValueError(f"Invalid rubric: {key}")
    meta = RUBRICS[key]
    matches = sorted(
        (r for r in records if r.get("rubric", "news") == key),
        key=lambda r: (r["published"], r["id"]), reverse=True
    )
    url = BASE + "/rubrics/" + key + "/"
    cards = "\n".join(
        '<a class="archive-card" href="../../' + escape(r["url"], quote=True) + '">'
        '<img loading="lazy" src="../../' + escape(r["cover"], quote=True) + '" alt="Обложка статьи">'
        '<span><small class="date">Опубликовано: ' + escape(publication_date(r["published"])) + '</small>'
        '<h3>' + escape(r["title"]) + '</h3>'
        '<p>' + escape(r["summary"]) + '</p></span>'
        '<span aria-hidden="true">↗</span></a>'
        for r in matches
    ) or '<p class="summary">Проверенные материалы этой рубрики скоро появятся.</p>'
    robots = '' if matches else '<meta name="robots" content="noindex, follow">'
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{escape(meta["description"], quote=True)}">
<meta property="og:title" content="{escape(meta["name"], quote=True)} — ХПИИ">
<meta property="og:url" content="{url}">
<link rel="canonical" href="{url}">{robots}
<link rel="stylesheet" href="../../assets/site.css"><title>{escape(meta["name"])} — ХПИИ</title></head>
<body><header class="header"><div class="wrap bar">
<a class="logo" href="../../index.html"><span class="badge">ХПИ</span><span>ХРОНИКИ<br>ПИКИРУЮЩЕГО ИИ<small>НОВОСТИ БЕЗ ИСТЕРИКИ</small></span></a>
<nav class="menu"><a href="../../index.html">Главная</a><a href="../../articles/">Все статьи</a></nav></div></header>
<main class="wrap"><div class="overline"><span>ХПИИ / Тематическая рубрика</span></div>
<h1>{escape(meta["name"])}</h1><p class="summary">{escape(meta["description"])}</p>
<nav class="rubric-navigation" aria-label="Рубрики">{navigation("../../")}</nav>
<section class="archive"><h2>Публикации — {len(matches)}</h2>{cards}</section></main>
<footer class="footer"><div class="wrap">Хроники Пикирующего ИИ</div></footer>
<script defer src="../../assets/social-footer.js"></script></body></html>
'''


def render_all(records, root):
    return {root / "rubrics" / key / "index.html": render_page(key, records)
            for key in RUBRICS}


def populated(records):
    return [key for key in RUBRICS if any(r.get("rubric", "news") == key for r in records)]
