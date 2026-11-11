"""Public, controlled company/product taxonomy for the static HPII site.

Only editor-curated published article IDs appear. No text scanning, external
requests, automatic publishing, or changes to approved story content.
"""
import argparse
from html import escape
import json
from pathlib import Path
from datetime import date
import re

ENTITY_KEY = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
ARTICLE_PATH = re.compile(r"articles/[a-z0-9]+(?:-[a-z0-9]+)*/\Z")
SAFE_COVER = re.compile(r"assets/[a-z0-9][a-z0-9/_-]*\.(?:webp|png|jpg|jpeg|svg)\Z")


def validate_public_registry(registry, records):
    """Separate public validation: historic articles may use local SVG covers.

    The experimental pilot's stricter JPEG/WebP/PNG contract is not relaxed.
    """
    if (not isinstance(registry, dict) or registry.get("schema_version") != 1
            or set(registry) != {"schema_version", "note", "companies", "products"}):
        raise ValueError("Invalid public entity registry schema")
    if not isinstance(registry["note"], str) or not registry["note"].strip():
        raise ValueError("Missing registry note")
    if not isinstance(records, list):
        raise ValueError("Published article index must be a list")
    known = {}
    for row in records:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("Invalid published article record")
        if row["id"] in known:
            raise ValueError("Duplicate published article ID")
        known[row["id"]] = row
    companies = set()
    for kind in ("companies", "products"):
        entries = registry[kind]
        if not isinstance(entries, list) or not entries:
            raise ValueError("Expected nonempty controlled entity lists")
        keys = set()
        for entry in entries:
            required = ({"key", "name", "description", "article_ids"} if kind == "companies"
                        else {"key", "name", "description", "company", "article_ids"})
            if not isinstance(entry, dict) or set(entry) != required:
                raise ValueError("Unknown/invalid entity metadata fields")
            key = entry["key"]
            if not isinstance(key, str) or not ENTITY_KEY.fullmatch(key) or key in keys:
                raise ValueError("Invalid or duplicate entity key")
            keys.add(key)
            if not all(isinstance(entry.get(k), str) and entry[k].strip()
                       for k in ("name", "description")):
                raise ValueError("Missing entity name or description")
            ids = entry["article_ids"]
            if (not isinstance(ids, list) or not ids or
                    any(not isinstance(i, str) for i in ids) or
                    len(ids) != len(set(ids))):
                raise ValueError("Invalid/repeated curated article IDs")
            for article_id in ids:
                if article_id not in known:
                    raise ValueError("Unknown unpublished article " + article_id)
                row = known[article_id]
                if (row.get("url") != "articles/" + article_id + "/" or
                        not ARTICLE_PATH.fullmatch(row["url"])):
                    raise ValueError("Invalid published article path " + article_id)
                if not all(isinstance(row.get(k), str) and row[k]
                           for k in ("title", "summary", "published", "cover")):
                    raise ValueError("Incomplete published article " + article_id)
                if not SAFE_COVER.fullmatch(row["cover"]):
                    raise ValueError("Unsafe published article cover " + article_id)
                date.fromisoformat(row["published"])
        if kind == "companies":
            companies = keys
        elif any(entry["company"] not in companies for entry in entries):
            raise ValueError("Product must refer to a registered company")
    return known

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



def render_article_entity_nav(slug, registry):
    """Return links for explicitly curated assignments, never inferred matches.

    Links appear only when the article ID is listed in the manually reviewed
    public registry. No content or editorial Markdown is consulted.
    """
    links = []
    for kind in ("companies", "products"):
        for entry in registry[kind]:
            if slug not in entry["article_ids"]:
                continue
            link = "../../entities/" + kind + "/" + entry["key"] + "/"
            icon = "../../assets/entity-icons/" + entry["key"] + ".svg"
            links.append(
                '<a href="' + e(link) + '">'
                '<img src="' + e(icon) + '" alt="" loading="lazy">'
                + e(entry["name"]) + '</a>'
            )
    if not links:
        return ""
    return (
        '<nav class="article-entity-links" aria-label="Компании и продукты статьи">'
        '<span class="article-entity-links-label">Компании и продукты</span>'
        + "".join(links) + '</nav>'
    )


def inject_article_entity_nav(page, slug, registry):
    """One-time navigation-only upgrade of existing published article HTML.

    The literal HTML from the cover onward is preserved byte-for-byte.
    Only the article-title header and a scoped style link may change.
    """
    nav = render_article_entity_nav(slug, registry)
    if not nav:
        return page
    css = '<link rel="stylesheet" href="../../assets/entities.css">'
    if 'class="article-entity-links"' in page:
        if page.count(nav) != 1 or page.count(css) != 1:
            raise ValueError("Unrecognized pre-existing company/product nav: " + slug)
        return page
    cover = '<figure class="cover">'
    if page.count(cover) != 1:
        raise ValueError("Unexpected article-cover boundary: " + slug)
    start, end = page.split(cover, 1)
    if start.count('<div class="article-title">') != 1:
        raise ValueError("Unexpected article title layout: " + slug)
    close = '</div>'
    if not start.rstrip().endswith(close):
        raise ValueError("Article header does not end at cover: " + slug)
    idx = start.rfind(close)
    start = start[:idx] + nav + start[idx:]
    if css in start:
        raise ValueError("Company/product stylesheet already present: " + slug)
    base_css = '<link rel="stylesheet" href="../../assets/site.css">'
    if start.count(base_css) != 1:
        raise ValueError("Missing article base stylesheet: " + slug)
    start = start.replace(base_css, base_css + '\n' + css, 1)
    return start + cover + end

def render_index(registry):
    sections = []
    for kind, title in (("companies", "Компании"), ("products", "Продукты")):
        items = sorted(registry[kind], key=lambda entry: entry["name"].casefold())
        links = "".join(
            '<a class="topic-index-link entity-tile" href="' +
            kind + '/' + e(entry["key"]) + '/">' +
            icon_markup(entry["key"], "../") +
            '<span class="entity-tile__copy"><strong>' + e(entry["name"]) +
            '</strong><span>' + str(len(entry["article_ids"])) +
            ' материалов в подборке</span></span></a>'
            for entry in items
        )
        sections.append(
            '<section data-entity-section><h2>' + title + ' — ' + str(len(items)) + '</h2>'
            '<nav class="topic-index-grid" aria-label="' + title + '">' +
            links + '</nav></section>'
        )
    total = len(registry["companies"]) + len(registry["products"])
    content = (
        '<div class="overline">ХПИИ / Каталог</div>'
        '<h1>Компании и продукты</h1>'
        '<p class="summary">Новости об участниках индустрии ИИ. '
        'В каталог попадают только материалы с подтверждённой редакцией связью; '
        'подборки пополняются постепенно.</p>'
        '<div class="entity-search" role="search">'
        '<label for="entity-filter">Найти компанию или продукт</label>'
        '<input id="entity-filter" type="search" autocomplete="off" '
        'placeholder="Например, NVIDIA, Claude, Grok">'
        '<p id="entity-filter-status" aria-live="polite">В справочнике ' +
        str(total) + ' названий</p></div>' + "".join(sections)
        + '<script defer src="../assets/entity-search.js"></script>'
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
    known = validate_public_registry(registry, records)
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
