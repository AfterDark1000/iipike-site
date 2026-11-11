#!/usr/bin/env python3
"""Read-only, opt-in pilot of company/product pages for HPII.

Does NOT alter news.json, approved articles, Dzen, sitemap or publication jobs.
Only explicitly reviewed article IDs appear. The experiment is intentionally
noindex and lives entirely under /lab/entities/.
"""
import argparse
from html import escape
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "entity_pilot.json"
ARTICLE = re.compile(r"articles/[a-z0-9]+(?:-[a-z0-9]+)*/\Z")
KEY = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря")


def validate(manifest, records):
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("Invalid entity pilot schema")
    if set(manifest) != {"schema_version", "note", "companies", "products"}:
        raise ValueError("Unknown entity pilot fields")
    if not isinstance(records, list):
        raise ValueError("Published catalog must be an array")
    known = {row["id"]: row for row in records if isinstance(row, dict) and "id" in row}
    if len(known) != len(records):
        raise ValueError("Invalid/duplicate published catalog IDs")
    companies = set()
    for kind in ("companies", "products"):
        entries = manifest[kind]
        if not isinstance(entries, list) or not entries:
            raise ValueError("Expected a nonempty pilot registry")
        keys = set()
        for entry in entries:
            required = ({"key", "name", "description", "article_ids"}
                        if kind == "companies" else
                        {"key", "name", "company", "description", "article_ids"})
            if not isinstance(entry, dict) or set(entry) != required:
                raise ValueError("Invalid entity metadata fields")
            key = entry["key"]
            if not isinstance(key, str) or not KEY.fullmatch(key) or key in keys:
                raise ValueError("Invalid/duplicate entity key")
            keys.add(key)
            for k in ("name", "description"):
                if not isinstance(entry[k], str) or not entry[k].strip():
                    raise ValueError("Empty entity display text")
            ids = entry["article_ids"]
            if (not isinstance(ids, list) or not ids or
                    len(ids) != len(set(ids))):
                raise ValueError("Empty or duplicate article assignments")
            for article_id in ids:
                if article_id not in known:
                    raise ValueError("Unpublished/unknown article: " + str(article_id))
                row = known[article_id]
                if row.get("url") != "articles/" + article_id + "/" or not ARTICLE.fullmatch(row["url"]):
                    raise ValueError("Unsafe article path")
                if not all(isinstance(row.get(k), str) and row[k]
                           for k in ("title", "summary", "cover", "published")):
                    raise ValueError("Incomplete article metadata")
                if not re.fullmatch(r"assets/[a-z0-9][a-z0-9/_-]*\.(?:webp|png|jpg|jpeg|svg)", row["cover"]):
                    raise ValueError("Unsafe cover path")
                from datetime import date
                date.fromisoformat(row["published"])
        if kind == "companies":
            companies = keys
        else:
            if any(e["company"] not in companies for e in entries):
                raise ValueError("Product must point to a registered company")
    return known


def e(value):
    return escape(str(value), quote=True)


def date_ru(iso):
    year, month, day = map(int, iso.split("-"))
    return str(day) + " " + MONTHS[month-1] + " " + str(year)


def shell(title, desc, root, content):
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex,nofollow,noarchive">'
            '<meta name="description" content="' + e(desc) + '">'
            '<title>' + e(title) + ' — ХПИИ (пилот)</title>'
            '<link rel="stylesheet" href="' + root + 'assets/site.css">' 
            '<link rel="stylesheet" href="' + root + 'lab/entities/pilot-icons.css"></head>'
            '<body><header class="header"><div class="wrap bar">'
            '<a class="logo" href="' + root + '"><span class="badge">ХПИ</span>'
            '<span>ХРОНИКИ<br>ПИКИРУЮЩЕГО ИИ<small>НОВОСТИ БЕЗ ИСТЕРИКИ</small></span></a>'
            '<nav class="menu"><a href="' + root + '">Главная</a>'
            '<a href="' + root + 'articles/">Все статьи</a></nav></div></header>'
            '<main class="wrap">' + content + '</main>'
            '<footer class="footer"><div class="wrap">Хроники Пикирующего ИИ · '
            'Экспериментальная страница</div></footer>'
            '<script defer src="' + root + 'assets/social-footer.js"></script></body></html>\n')


ENTITY_ICON_KEYS = frozenset({
    "google", "openai", "adobe", "disney", "xai", "anthropic",
    "chatgpt", "grok", "gemini", "claude", "firefly",
})


def icon_markup(key, root, *, large=False):
    """Locally hosted decorative brand icon; the name remains visible in text."""
    if key not in ENTITY_ICON_KEYS:
        raise ValueError("Unregistered entity icon: " + str(key))
    suffix = " entity-emblem--lg" if large else ""
    return ('<span class="entity-emblem entity-emblem--' + e(key) + suffix + '">'
            '<img loading="lazy" decoding="async" src="' + root +
            'lab/entities/icons/' + e(key) + '.svg" alt=""></span>')


def render_index(manifest):
    parts = []
    for kind, title in (("companies", "Компании"), ("products", "Продукты")):
        links = "".join(
            '<a class="topic-index-link entity-tile" href="' + kind + '/' + e(row["key"]) + '/">' +
            icon_markup(row["key"], "../../") +
            '<span class="entity-tile__copy"><strong>' + e(row["name"]) + '</strong><span>' +
            str(len(row["article_ids"])) + ' отобранных материалов</span></span></a>'
            for row in manifest[kind])
        parts.append('<section><h2>' + title + '</h2><nav class="topic-index-grid" aria-label="' +
                     title + '">' + links + '</nav></section>')
    body = ('<div class="overline">ХПИИ / Лаборатория</div>'
            '<h1>Компании и продукты</h1>'
            '<p class="summary"><strong>Тестовая версия.</strong> Это ручная выборка, '
            'а не полный архив: здесь только проверенные связи. '
            'Пока не встроено в навигацию сайта.</p>' + "".join(parts))
    return shell("Компании и продукты", "Тестовая навигация по участникам новостей ИИ.",
                 "../../", body)


def render_detail(kind, entry, records):
    root = "../../../../"
    rows = sorted((records[i] for i in entry["article_ids"]),
                  key=lambda r: (r.get("published_at_utc", r["published"]), r["id"]), reverse=True)
    cards = "".join(
        '<a class="archive-card" href="' + root + e(r["url"]) + '">'
        '<img loading="lazy" src="' + root + e(r["cover"]) + '" alt="Обложка статьи">'
        '<span><small class="date">' + e(date_ru(r["published"])) + '</small>'
        '<h3>' + e(r["title"]) + '</h3><p>' + e(r["summary"]) + '</p></span>'
        '<span aria-hidden="true">↗</span></a>'
        for r in rows)
    owner = ('<p class="date">Разработчик: <a href="../../companies/' +
             e(entry["company"]) + '/">' + e(entry["company"]) + '</a></p>'
             if kind == "products" else "")
    body = ('<div class="overline">ХПИИ / Лаборатория / ' +
            ("Компании" if kind == "companies" else "Продукты") + '</div>'
            '<div class="entity-hero">' + icon_markup(entry["key"], root, large=True) +
            '<div><h1>' + e(entry["name"]) + '</h1>'
            '<p class="summary">' + e(entry["description"]) + '</p></div></div>' + owner +
            '<p class="date">' + str(len(rows)) + ' отобранных материалов · '
            'пилот, не полный архив</p>'
            '<p><a href="../../">← Все компании и продукты</a></p>'
            '<section class="archive"><h2>Публикации</h2>' + cards + '</section>')
    return shell(entry["name"], entry["description"], root, body)


def render_all(manifest, records, root=ROOT):
    known = validate(manifest, records)
    root = Path(root)
    dest = root / "lab" / "entities"
    result = {dest / "index.html": render_index(manifest)}
    for kind in ("companies", "products"):
        for entry in manifest[kind]:
            result[dest / kind / entry["key"] / "index.html"] = render_detail(kind, entry, known)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Compare committed pages without changing files")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
    for path, content in render_all(manifest, rows).items():
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                parser.exit(1, "Entity pilot page outdated: " + str(path) + "\n")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    print("Entity pilot pages checked" if args.check else "Entity pilot pages updated")


if __name__ == "__main__":
    main()
