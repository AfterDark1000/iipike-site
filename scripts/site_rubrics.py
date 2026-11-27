"""Canonical HPII rubrics: editorial categories, not extra copies of articles."""
from html import escape
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from itertools import groupby

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
    "made-with-ai": {
        "slug": "made-with-ai", "name": "Сделано с ИИ",
        "description": "Игры, фильмы, виртуальные миры, музыка и изобретения людей, созданные с помощью нейросетей. Проверяем, что авторы действительно показали.",
    },
}


MONTHS_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def publication_sort_key(row):
    """One canonical newest-first chronology across home, archive and rubrics.

    Historical imports with day-only precision use midnight that day;
    newly published articles use their actual UTC publication timestamp.
    """
    return (row.get("published_at_utc") or row["published"] + "T00:00:00Z",
            row["id"])


def publication_date(value):
    """Show an original historical publication day in reader-friendly Russian."""
    day = date.fromisoformat(value)
    return f"{day.day} {MONTHS_RU[day.month - 1]} {day.year}"


def publication_label(row):
    """Reader-visible publication day and, when known, local HH:MM (UTC+05).

    Historic day-only records never receive invented publication minutes.
    """
    stamp = row.get("published_at_utc")
    if stamp and row.get("publication_date_precision") != "day":
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            raise ValueError("Publication timestamp missing UTC offset")
        local = moment.astimezone(ZoneInfo("Asia/Yekaterinburg"))
        return f"{publication_date(local.date().isoformat())} · {local:%H:%M}"
    return publication_date(row["published"])


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


def render_card(r):
    label = publication_label(r)
    _, _, time = label.partition(" · ")
    return (
        '<a class="archive-card" href="../../' + escape(r["url"], quote=True) + '">'
        '<span class="rubric-time" aria-label="' + escape(label, quote=True) + '">' + time + '</span>'
        '<img loading="lazy" src="../../' + escape(r["cover"], quote=True) + '" alt="Обложка статьи">'
        '<div class="rubric-copy"><h3>' + escape(r["title"]) + '</h3>'
        '<p>' + escape(r["summary"]) + '</p></div>'
        '<span class="rubric-arrow" aria-hidden="true">↗</span></a>'
    )


def render_page(key, records):
    if key not in RUBRICS:
        raise ValueError(f"Invalid rubric: {key}")
    meta = RUBRICS[key]
    matches = sorted(
        (r for r in records if r.get("rubric", "news") == key),
        key=publication_sort_key, reverse=True
    )
    url = BASE + "/rubrics/" + key + "/"
    days = []
    for day, rows in groupby(matches, key=lambda r: publication_label(r).partition(" · ")[0]):
        days.append('<section class="rubric-day"><h2 class="rubric-day-title">' +
                    escape(day) + '</h2><div class="rubric-day-list">' +
                    "\n".join(render_card(r) for r in rows) + '</div></section>')
    cards = "\n".join(days) or '<p class="rubric-empty">Проверенные материалы этой рубрики скоро появятся.</p>'
    robots = '' if matches else '<meta name="robots" content="noindex, follow">'
    nav = "\n".join('<a href="' + rubric_link(k, "../../") + '"' +
                    (' aria-current="page"' if k == key else '') + '>' +
                    escape(m["name"]) + '</a>' for k, m in RUBRICS.items())
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#f6f3eb">
<meta name="description" content="{escape(meta["description"], quote=True)}">
<meta property="og:title" content="{escape(meta["name"], quote=True)} — ХПИИ">
<meta property="og:url" content="{url}">
<link rel="canonical" href="{url}">{robots}
<link rel="icon" href="../../assets/icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="../../assets/site.css"><title>{escape(meta["name"])} — ХПИИ</title></head>
<body class="home-v1 rubric-r2" data-rubric="{key}"><header class="header"><div class="wrap bar">
<a class="logo" href="../../index.html" aria-label="Хроники Пикирующего ИИ — главная"><span class="badge" aria-hidden="true">ХПИ</span><span>ХРОНИКИ<br>ПИКИРУЮЩЕГО ИИ<small>НОВОСТИ БЕЗ ИСТЕРИКИ</small></span></a>
<nav class="menu home-menu" aria-label="Основное меню"><a href="../../articles/">Все статьи</a><a href="../../briefs/">Коротко</a><a href="../../dossier/">Досье</a><a href="../../entities/">Компании и продукты</a></nav></div></header>
<div class="home-v1-rubrics"><div class="wrap"><nav class="rubric-navigation" aria-label="Рубрики">{nav}</nav></div></div>
<main class="wrap rubric-main"><div class="rubric-head"><div><span class="rubric-kicker">ХПИИ / Рубрика</span>
<h1>{escape(meta["name"])}</h1><p class="rubric-deck">{escape(meta["description"])}</p></div>
<span class="rubric-count">Материалов: {len(matches)}</span></div>
{cards}</main>
<footer class="footer"><div class="wrap home-v1-footer"><span>Хроники Пикирующего ИИ · Новости без истерики</span><nav><a href="../../registry/">Архив Дзена</a><a href="../../drafts/">Лаборатория редакции</a><a href="../../feed.xml">RSS</a></nav></div></footer>
<script defer src="../../assets/social-footer.js"></script></body></html>
'''


def render_all(records, root):
    return {root / "rubrics" / key / "index.html": render_page(key, records)
            for key in RUBRICS}


def populated(records):
    return [key for key in RUBRICS if any(r.get("rubric", "news") == key for r in records)]
