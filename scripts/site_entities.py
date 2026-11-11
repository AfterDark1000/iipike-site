"""Public, controlled company/product taxonomy for the static HPII site.

Only editor-curated published article IDs appear. No text scanning, external
requests, automatic publishing, or changes to approved story content.
"""
import argparse
from html import escape
import json
from pathlib import Path
from scripts.build_entity_pilot import validate as validate_curated
from scripts.site_rubrics import publication_date, RUBRICS

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://iipike.ru"
REGISTRY = "data/entity_registry.json"


def load_registry(root=ROOT):
    return json.loads((Path(root) / REGISTRY).read_text(encoding="utf-8"))


def entity_urls(registry):
    """Stable, allowlisted public URLs for sitemap generation."""
    return ([BASE + "/entities/"] +
            [BASE + "/entities/" + kind + "/" + entry["key"] + "/"
             for kind in ("companies", "products") for entry in registry[kind]])


def e(value):
    return escape(str(value), quote=True)


def icon_markup(key, prefix, *, large=False):
    if not isinstance(key, str) or not key.isascii() or not key.replace("-", "").isalnum():
        raise ValueError("Invalid icon key")
    css = " entity-emblem--lg" if large else ""
    return ('<span class="entity-emblem entity-emblem--' + e(key) + css + '">'
            '<img loading="lazy" decoding="async" src="' + prefix +
            'assets/entity-icons/' + e(key) + '.svg" alt=""></span>')


def shell(title, description, prefix, canonical, content):
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="description" content="' + e(description) + '">'
        '<link rel="canonical" href="' + e(canonical) + '">'
        '<meta property="og:title" content="' + e(title) + ' — ХПИИ">'
        '<meta property="og:url" content="' + e(canonical) + '">'
        '<title>' + e(title) + ' — ХПИИ</title>'
        '<link rel="stylesheet" href="' + prefix + 'assets/site.css">'
        '<link rel="stylesheet" href="' + prefix + 'assets/entities.css">'
        '</head><body><header class="header"><div class="wrap bar">'
        '<a class="logo" href="' + prefix + '"><span class="badge">ХПИ</span>'
        '<span>ХРОНИКИ<br>ПИКИРУЮЩЕГО ИИ<small>НОВОСТИ БЕЗ ИСТЕРИКИ</small></span></a>'
        '<nav class="menu"><a href="' + prefix + '">Главная</a>'
        '<a href="' + prefix + 'articles/">Все статьи</a></nav></div></header>'
        '<main class="wrap">' + content + '</main>'
        '<footer class="footer"><div class="wrap">Хроники Пикирующего ИИ</div></footer>'
        '<script defer src="' + prefix + 'assets/social-footer.js"></script>'
        '</body></html>\n'
    )


def render_index(registry):
    sections = []
    for kind, title in (("companies", "Компании"), ("products", "Продукты")):
        links = "".join(
            '<a class="topic-index-link entity-tile" href="' +
            kind + '/' + e(entry["key"]) + '/">' +
            icon_markup(entry["key"], "../") +
            '<span class="entity-tile__copy"><strong>' + e(entry["name"]) +
            '</strong><span>' + str(len(entry["article_ids"])) +
            ' материалов в подборке</span></span></a>'
            for entry in registry[kind]
        )
        sections.append(
            '<section><h2>' + title + '</h2>'
            '<nav class="topic-index-grid" aria-label="' + title + '">' +
            links + '</nav></section>'
        )
    content = (
        '<div class="overline">ХПИИ / Каталог</div>'
        '<h1>Компании и продукты</h1>'
        '<p class="summary">Новости об участниках индустрии ИИ. '
        'В каталог попадают только материалы с подтверждённой редакцией связью; '
        'подборки пополняются постепенно.</p>' + "".join(sections)
    )
    return shell("Компании и продукты",
                 "Новости компаний и продуктов ИИ: Google, OpenAI, Anthropic, Adobe, Disney, Grok и другие.",
                 "../", BASE + "/entities/", content)


def render_entity(kind, entry, records, companies):
    if kind not in ("companies", "products"):
        raise ValueError("Invalid entity type")
    prefix = "../../../"
    rows = sorted(
        (records[article_id] for article_id in entry["article_ids"]),
        key=lambda row: (row.get("published_at_utc", row["published"]), row["id"]),
        reverse=True,
    )
    cards = "".join(
        '<a class="archive-card" href="' + prefix + e(row["url"]) + '">'
        '<img loading="lazy" src="' + prefix + e(row["cover"]) + '" alt="Обложка статьи">'
        '<span><small class="date">' + e(publication_date(row["published"])) +
        ' · ' + e(RUBRICS[row.get("rubric", "news")]["name"]) + '</small>'
        '<h3>' + e(row["title"]) + '</h3><p>' + e(row["summary"]) + '</p></span>'
        '<span aria-hidden="true">↗</span></a>'
        for row in rows
    )
    owner = (
        '<p class="date">Разработчик: <a href="../../companies/' +
        e(entry["company"]) + '/">' + e(companies[entry["company"]]) + '</a></p>'
        if kind == "products" else ""
    )
    content = (
        '<div class="overline">ХПИИ / Каталог / ' +
        ("Компании" if kind == "companies" else "Продукты") + '</div>'
        '<div class="entity-hero">' + icon_markup(entry["key"], prefix, large=True) +
        '<div><h1>' + e(entry["name"]) + '</h1>'
        '<p class="summary">' + e(entry["description"]) + '</p></div></div>' + owner +
        '<p class="date">' + str(len(rows)) + ' материалов в редакционной подборке</p>'
        '<p><a href="../../">← Компании и продукты</a></p>'
        '<section class="archive"><h2>Публикации</h2>' + cards + '</section>'
    )
    url = BASE + "/entities/" + kind + "/" + entry["key"] + "/"
    return shell(entry["name"], entry["description"], prefix, url, content)


def render_all_entities(records, root=ROOT):
    """Build only public /entities/ pages from the reviewed static registry."""
    root = Path(root)
    registry = load_registry(root)
    known = validate_curated(registry, records)
    companies = {x["key"]: x["name"] for x in registry["companies"]}
    outputs = {root / "entities" / "index.html": render_index(registry)}
    for kind in ("companies", "products"):
        for entry in registry[kind]:
            outputs[root / "entities" / kind / entry["key"] / "index.html"] = (
                render_entity(kind, entry, known, companies)
            )
    return outputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rows = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
    for path, content in render_all_entities(rows, ROOT).items():
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                parser.exit(1, "Entity page outdated: " + str(path) + "\n")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    print("Public entity catalog checked" if args.check else "Public entity catalog updated")


if __name__ == "__main__":
    main()
