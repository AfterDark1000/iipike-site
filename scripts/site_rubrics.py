"""Canonical HPII rubrics: editorial categories, not extra copies of articles."""
from html import escape
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from itertools import groupby
import re

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



LISTING_PAGE_SIZE = 20
_LISTING_SECTION = re.compile(
    r'<section class="(?P<kind>rubric|brief)-day"><h2 class="(?P=kind)-day-title">'
    r'(?P<day>[^<]+)</h2><div class="(?P=kind)-day-list">(?P<cards>.*?)</div></section>', re.S)
_LISTING_CARD = {
    "rubric": re.compile(r'<a class="archive-card" href="[^"]+">.*?</a>', re.S),
    "brief": re.compile(r'<article class="brief-item" id="[^"]+">.*?</article>', re.S),
}
_LISTING_NEXT = re.compile(r'<a class="listing-more" data-listing-next href="(page-[0-9]+\.html)">')
_LISTING_FILENAME = re.compile(r'page-([2-9]|[1-9][0-9]+)\.html\Z')


def paginate_listing(index_path, html):
    """Partition only canonical generated day sections into real crawlable pages."""
    sections = list(_LISTING_SECTION.finditer(html))
    if not sections:
        return {index_path: html}
    kind = sections[0]["kind"]
    rows = []
    for section in sections:
        if section["kind"] != kind:
            raise ValueError("Mixed listing kinds")
        cards = _LISTING_CARD[kind].findall(section["cards"])
        if "\n".join(cards) != section["cards"]:
            raise ValueError("Unexpected generated listing markup")
        rows.extend((section["day"], card) for card in cards)
    if len(rows) <= LISTING_PAGE_SIZE:
        return {index_path: html}
    first, last = sections[0].start(), sections[-1].end()
    if "\n".join(s.group(0) for s in sections) != html[first:last]:
        raise ValueError("Unexpected markup between listing days")
    canonical = re.search(r'<link rel="canonical" href="(https://iipike\.ru/[^"]+/)">', html)
    if canonical is None:
        raise ValueError("Missing listing canonical")
    base_url = canonical.group(1)
    result = {}
    for start in range(0, len(rows), LISTING_PAGE_SIZE):
        number = start // LISTING_PAGE_SIZE + 1
        filename = "index.html" if number == 1 else f"page-{number}.html"
        days = []
        for day, group in groupby(rows[start:start+LISTING_PAGE_SIZE], key=lambda item: item[0]):
            days.append(f'<section class="{kind}-day"><h2 class="{kind}-day-title">{day}</h2>'
                        f'<div class="{kind}-day-list">' +
                        "\n".join(card for _, card in group) + '</div></section>')
        block = '<div data-listing-content>' + "\n".join(days) + '</div>'
        if start + LISTING_PAGE_SIZE < len(rows):
            block += (f'<div class="listing-more-wrap"><a class="listing-more" data-listing-next '
                      f'href="page-{number+1}.html">Показать ещё</a></div>')
        rendered = html[:first] + block + html[last:]
        if number > 1:
            rendered = rendered.replace(f'href="{base_url}"', f'href="{base_url}{filename}"', 1)
            rendered = rendered.replace(f'content="{base_url}"', f'content="{base_url}{filename}"', 1)
        result[index_path.with_name(filename)] = rendered
    return result


def read_listing_pages(index_path):
    current, pages, seen = index_path, [], set()
    while True:
        if current in seen:
            raise ValueError("Listing cycle")
        seen.add(current)
        html = current.read_text(encoding="utf-8")
        pages.append(html)
        links = _LISTING_NEXT.findall(html)
        if not links:
            return pages
        if len(links) != 1 or not _LISTING_FILENAME.fullmatch(links[0]):
            raise ValueError("Invalid listing continuation")
        current = current.with_name(links[0])


def listing_markup(index_path):
    return "\n".join(read_listing_pages(index_path))


def listing_days(labels):
    return [day for i in range(0, len(labels), LISTING_PAGE_SIZE)
            for day, _ in groupby(labels[i:i+LISTING_PAGE_SIZE],
                                  key=lambda label: label.partition(" · ")[0])]


def render_all(records, root):
    outputs = {}
    for key in RUBRICS:
        outputs.update(paginate_listing(root / "rubrics" / key / "index.html",
                                        render_page(key, records)))
    return outputs


def populated(records):
    return [key for key in RUBRICS if any(r.get("rubric", "news") == key for r in records)]
