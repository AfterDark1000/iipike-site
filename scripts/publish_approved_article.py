#!/usr/bin/env python3
"""Publish *explicitly approved* articles to the static HPII website.

No network access, no Dzen/social API calls, and no unattended publishing.
An editor must place a reviewed JSON in content/approved/<slug>.json,
then explicitly run --publish. Default operation is read-only preflight.
"""
import argparse
import datetime as dt
from email.utils import format_datetime
import html
import json
from zoneinfo import ZoneInfo
from pathlib import Path
import re
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.site_rubrics import RUBRICS, render_all, populated, navigation, publication_date
from scripts.site_related import catalog_entries, validate_reference, validate_links, render_links
from scripts.site_home import update_home
BASE = "https://iipike.ru"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
ASSET = re.compile(r"assets/[a-zA-Z0-9/_-]+\.(?:png|jpg|jpeg|webp|svg)\Z")
TYPES = {"lead": "p", "p": "p", "h2": "h2"}
EDITORIAL_TZ = ZoneInfo("Asia/Yekaterinburg")


def quote(value):
    return html.escape(str(value), quote=True)


def need_text(doc, key, limit=5000):
    value = doc.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"Missing/invalid {key}")
    return value.strip()


def approved_article(root, slug):
    if not SLUG.fullmatch(slug):
        raise ValueError("Invalid article slug")
    path = root / "content" / "approved" / f"{slug}.json"
    if not path.is_file():
        raise ValueError(f"No approved source file: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("status") != "approved":
        raise ValueError("Article status must be explicitly approved")
    if data.get("slug") != slug:
        raise ValueError("Approved source slug does not match CLI argument")
    rubric = need_text(data, "rubric", 80)
    if rubric not in RUBRICS:
        raise ValueError("Invalid article rubric: " + rubric)
    references = data.get("related_dzen_ids", [])
    dzen_id = data.get("dzen_id")
    original_dt = None
    original_day = None
    if dzen_id is not None or references:
        catalog = catalog_entries(root)
        validate_links(references, catalog, current=dzen_id)
        if dzen_id is not None:
            entry = validate_reference(dzen_id, catalog)
            if data.get("dzen_url") != entry["dzen_url"]:
                raise ValueError("Dzen original URL mismatch with verified catalog")
            # The original Dzen publication timestamp is *the* editorial
            # publication timestamp: never invent a second site date.
            # Preserve source accuracy: when Dzen provides only its calendar day,
            # NEVER manufacture a midnight time or infer seconds from a Dzen ID.
            recorded = entry.get("published_at_utc") or ""
            source_day = entry.get("published_date") or ""
            if recorded:
                original_dt = dt.datetime.fromisoformat(recorded.replace("Z", "+00:00"))
                if original_dt.tzinfo is None:
                    raise ValueError("Historical Dzen timestamp is missing timezone")
            elif (source_day and entry.get("published_date_evidence")
                  == "dzen_itemprop_datePublished"
                  and entry.get("url_evidence") == "verified_on_public_dzen_page"
                  and entry.get("title_evidence") == "verified_on_public_dzen_page"):
                original_day = dt.date.fromisoformat(source_day)
            else:
                raise ValueError("Original Dzen publication date is unavailable or unverified")
    elif "dzen_url" in data:
        raise ValueError("Dzen URL requires a verified dzen_id")
    if "original_dzen_published_at_utc" in data:
        raise ValueError("Redundant original date: use published_at_utc for the original Dzen date")
    need_text(data, "approved_by", 100)
    dt.date.fromisoformat(need_text(data, "approved_at", 20))
    for k in ("title", "summary", "section", "source_title"):
        need_text(data, k, 500 if k != "summary" else 1500)
    dt.date.fromisoformat(need_text(data, "published", 20))
    if "event_date" in data:
        dt.date.fromisoformat(need_text(data, "event_date", 20))
    precision = data.get("publication_date_precision", "second")
    if precision == "day":
        if dzen_id is None or original_day is None or original_dt is not None:
            raise ValueError("Date-only records require a verified Dzen calendar date")
        if "published_at_utc" in data:
            raise ValueError("No artificial UTC timestamp allowed for date-only originals")
        if data["published"] != original_day.isoformat():
            raise ValueError("Visible date must match original Dzen datePublished")
        when = None
    elif precision == "second":
        stamp = need_text(data, "published_at_utc", 40)
        if not stamp.endswith("Z"):
            raise ValueError("published_at_utc must be explicitly UTC (Z)")
        when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if when.astimezone(EDITORIAL_TZ).date().isoformat() != data["published"]:
            raise ValueError("published must match the original timestamp in editorial timezone")
        if dzen_id is not None and when != original_dt:
            raise ValueError("Publication date must match verified original Dzen publication")
    else:
        raise ValueError("Unknown publication_date_precision")
    # Only meaningful, real editorial updates receive modification metadata.
    modified = data.get("modified_at_utc")
    if modified is not None:
        if not isinstance(modified, str) or not modified.endswith("Z"):
            raise ValueError("modified_at_utc must be ISO-8601 UTC with Z")
        changed_at = dt.datetime.fromisoformat(modified.replace("Z", "+00:00"))
        if ((when is not None and changed_at <= when) or
                (when is None and changed_at.astimezone(EDITORIAL_TZ).date() <= original_day)):
            raise ValueError("modified_at_utc must follow original publication")
        if changed_at > dt.datetime.now(dt.timezone.utc):
            raise ValueError("modified_at_utc cannot be in the future")
    source = need_text(data, "source_url", 2000)
    u = urlsplit(source)
    if (u.scheme != "https" or not u.hostname or u.username or u.password
            or u.port not in (None, 443) or any(ch.isspace() for ch in source)):
        raise ValueError("source_url must be a safe HTTPS URL")
    cover = need_text(data, "cover", 200)
    if (not ASSET.fullmatch(cover) or ".." in cover.split("/")
            or not (root / cover).is_file()):
        raise ValueError("cover must be an existing local assets image")
    paragraphs = data.get("paragraphs")
    if (not isinstance(paragraphs, list) or len(paragraphs) < 2
            or not isinstance(paragraphs[0], dict)
            or paragraphs[0].get("type") != "lead"):
        raise ValueError("Article requires a lead and at least another paragraph")
    for block in paragraphs:
        if not isinstance(block, dict) or block.get("type") not in TYPES:
            raise ValueError("Unsupported paragraph type")
        need_text(block, "text", 12000)
    return data


def render_article(data, records=None, catalog=None):
    slug = data["slug"]
    url = f"{BASE}/articles/{slug}/"
    title, summary = quote(data["title"]), quote(data["summary"])
    cover = f"../../{quote(data['cover'])}"
    rubric = data["rubric"]
    rubric_name = quote(RUBRICS[rubric]["name"])
    source_link = ""
    if data.get("dzen_id") and data.get("source_url") != data.get("dzen_url"):
        source_link = (
            '<p class="date"><a href="' + quote(data["dzen_url"])
            + '" target="_blank" rel="noopener noreferrer">Версия в Дзене ↗</a></p>'
        )
    modified = data.get("modified_at_utc")
    modified_meta = (
        '<meta property="article:modified_time" content="' + quote(modified) + '">'
        if modified else ""
    )
    published_meta = (
        '<meta property="article:published_time" content="' + quote(data["published_at_utc"]) + '">'
        if data.get("published_at_utc") else ""
    )
    # Dates in machine-readable metadata are the actual editorial publication
    # date (original Dzen when migrated) and optional substantive revision.
    structured = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": data["title"],
        "mainEntityOfPage": url,
        "inLanguage": "ru",
        "publisher": {"@type": "Organization", "name": "Хроники Пикирующего ИИ"},
        "datePublished": data.get("published_at_utc") or data["published"],
        "image": BASE + "/" + data["cover"],
    }
    if modified:
        structured["dateModified"] = modified
    if data.get("dzen_url"):
        structured["isBasedOn"] = data["dzen_url"]
    structured_json = json.dumps(structured, ensure_ascii=False).replace("<", "\\u003c")
    related_html = render_links(data.get("related_dzen_ids", []), records or [], catalog or {})
    provenance_only = data.get("source_url") == data.get("dzen_url")
    source_heading = "Архивная публикация" if provenance_only else "Первоисточник"
    body = "\n".join(
        f'<{TYPES[b["type"]]} class="lead">{quote(b["text"])}</p>'
        if b["type"] == "lead"
        else f'<{TYPES[b["type"]]}>{quote(b["text"])}</{TYPES[b["type"]]}>' for b in data["paragraphs"]
    )
    date = dt.date.fromisoformat(data["published"])
    months = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    label = f"{date.day} {months[date.month - 1]} {date.year}"
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{summary}"><meta property="og:type" content="article">
<meta property="og:title" content="{title}"><meta property="og:description" content="{summary}">
<meta property="og:image" content="{BASE}/{quote(data["cover"])}">
<meta property="og:url" content="{url}">{published_meta}{modified_meta}
<script type="application/ld+json">{structured_json}</script>
<link rel="canonical" href="{url}"><title>{title} — ХПИИ</title>
<link rel="stylesheet" href="../../assets/site.css">
<link rel="alternate" type="application/rss+xml" href="../../feed.xml" title="Новости ХПИИ">
<link rel="icon" href="../../assets/icon.svg" type="image/svg+xml"></head>
<body><header class="header"><div class="wrap bar">
<a class="logo" href="../../index.html"><span class="badge">ХПИ</span><span>ХРОНИКИ<br>ПИКИРУЮЩЕГО ИИ<small>НОВОСТИ БЕЗ ИСТЕРИКИ</small></span></a>
<nav class="menu"><a href="../">Статьи</a><a href="../../index.html">Главная</a></nav></div></header>
<main class="wrap"><div class="article-title"><a href="../">← Все статьи</a>
<p class="kicker"><a href="../../rubrics/{rubric}/">{rubric_name}</a> / {quote(data["section"])}</p><h1>{title}</h1>
<p class="summary">{summary}</p><p class="date">Опубликовано: {label}</p>{source_link}</div>
<figure class="cover"><img src="{cover}" alt="Обложка: {title}" width="1600" height="900"></figure>
<section class="article-body"><aside class="sources"><h3>{source_heading}</h3>
<a href="{quote(data["source_url"])}" target="_blank" rel="noopener noreferrer">{quote(data["source_title"])} ↗</a>
</aside><article class="article-text">{body}{related_html}</article></section></main>
<footer class="footer"><div class="wrap"><strong>Хроники Пикирующего ИИ</strong><p>Проверяем факты и указываем первоисточники.</p></div></footer>
<script defer src="../../assets/social-footer.js"></script></body></html>
'''


def render_catalog(records):
    ordered = sorted(records, key=lambda r: (r["published"], r["id"]), reverse=True)
    cards = "\n".join(
        f'<a class="archive-card" href="{quote(row["id"])}/">'
        f'<img loading="lazy" src="../{quote(row["cover"])}" alt="Обложка статьи">'
        f'<span><small class="date">{quote(publication_date(row["published"]))}'
        f' · {quote(RUBRICS[row.get("rubric", "news")]["name"])}</small>'
        f'<h3>{quote(row["title"])}</h3><p>{quote(row["summary"])}</p></span>'
        '<span aria-hidden="true">↗</span></a>' for row in ordered
    )
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Проверенные публикации Хроник Пикирующего ИИ с первоисточниками.">
<meta property="og:title" content="Все статьи — Хроники Пикирующего ИИ">
<meta property="og:url" content="{BASE}/articles/">
<link rel="canonical" href="{BASE}/articles/">
<link rel="stylesheet" href="../assets/site.css"><title>Все статьи — ХПИИ</title></head>
<body><header class="header"><div class="wrap bar">
<a class="logo" href="../index.html"><span class="badge">ХПИ</span><span>ХРОНИКИ<br>ПИКИРУЮЩЕГО ИИ<small>НОВОСТИ БЕЗ ИСТЕРИКИ</small></span></a>
<nav class="menu"><a href="../index.html">Главная</a><a href="../feed.xml">RSS</a></nav></div></header>
<main class="wrap"><div class="overline"><span>ХПИИ / Редакционная лента</span></div>
<h1>Все статьи</h1><p class="summary">Опубликованные материалы с проверенными источниками. Черновики здесь не появляются.</p>
<nav class="rubric-navigation" aria-label="Рубрики">{navigation("../")}</nav>
<section class="archive"><h2>Публикации</h2>{cards}</section></main>
<footer class="footer"><div class="wrap">Хроники Пикирующего ИИ</div></footer>
<script defer src="../assets/social-footer.js"></script></body></html>
'''


def render_feed(records, old_feed):
    import xml.sax.saxutils as sx
    old = {}
    try:
        tree = ET.fromstring(old_feed)
        for x in tree.findall("./channel/item"):
            link = x.findtext("link", "")
            slug = link.rstrip("/").split("/")[-1]
            old[slug] = (x.findtext("guid"), x.findtext("pubDate"))
    except ET.ParseError as exc:
        raise ValueError("Existing RSS invalid") from exc
    items = []
    for row in sorted(records, key=lambda r: (r["published"], r["id"]), reverse=True):
        url = BASE + "/" + row["url"]
        guid, published = old.get(row["id"], (None, None))
        guid = guid or url
        if not published:
            raw = row.get("published_at_utc")
            published = (format_datetime(dt.datetime.fromisoformat(raw.replace("Z", "+00:00")))
                         if raw else None)
        # RSS 2.0 pubDate requires an RFC 822 time. Omit it if only the source
        # calendar day is verified; an invented clock time would be misleading.
        pubdate = "<pubDate>" + sx.escape(published) + "</pubDate>" if published else ""
        items.append(
            "<item><title>" + sx.escape(row["title"]) + "</title><link>" + sx.escape(url)
            + '</link><guid isPermaLink="true">' + sx.escape(guid) + "</guid>"
            + "<description>" + sx.escape(row["summary"]) + "</description>"
            + pubdate + "</item>"
        )
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
            '<title>Хроники Пикирующего ИИ</title><link>' + BASE + '/</link>'
            '<description>Новости об искусственном интеллекте с первоисточниками</description>'
            '<language>ru-RU</language>' + "".join(items) + '</channel></rss>\n')


def render_sitemap(records):
    from xml.sax.saxutils import escape as xml_escape
    urls = ([BASE + "/", BASE + "/articles/"]
            + [BASE + "/rubrics/" + key + "/" for key in populated(records)]
            + [BASE + "/" + r["url"] for r in records])
    updates = {BASE + "/" + row["url"]: row["modified_at_utc"] for row in records
               if row.get("modified_at_utc")}
    def xml_entry(url):
        stamp = updates.get(url)
        lastmod = f"<lastmod>{xml_escape(stamp)}</lastmod>" if stamp else ""
        return f"  <url><loc>{xml_escape(url)}</loc>{lastmod}</url>\n"
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "".join(xml_entry(url) for url in urls)
            + "</urlset>\n")


def publish(root, slug, apply=False):
    data = approved_article(root, slug)
    entries_path = root / "news.json"
    entries = json.loads(entries_path.read_text(encoding="utf-8"))
    dest = root / "articles" / slug / "index.html"
    if dest.exists() or any(r["id"] == slug or r["url"] == f"articles/{slug}/" for r in entries):
        raise ValueError("Already published: cannot overwrite an existing article")
    row = {k: data[k] for k in ("title", "summary", "published",
                               "source_url", "cover", "rubric")}
    if data.get("published_at_utc"):
        row["published_at_utc"] = data["published_at_utc"]
    if data.get("publication_date_precision") == "day":
        row["publication_date_precision"] = "day"
    if "event_date" in data:
        row["event_date"] = data["event_date"]
    # published/published_at_utc = original editorial publication time.
    for key in ("dzen_id", "dzen_url", "modified_at_utc"):
        if key in data:
            row[key] = data[key]
    row["id"] = slug
    row["url"] = f"articles/{slug}/"
    updated = entries + [row]
    catalog = catalog_entries(root) if data.get("dzen_id") or data.get("related_dzen_ids") else {}
    outputs = {
        dest: render_article(data, updated, catalog),
        entries_path: json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
        root / "articles" / "index.html": render_catalog(updated),
        root / "feed.xml": render_feed(updated, (root / "feed.xml").read_text(encoding="utf-8")),
        root / "sitemap.xml": render_sitemap(updated),
        root / "index.html": update_home((root / "index.html").read_text(encoding="utf-8"), updated),
    }
    outputs.update(render_all(updated, root))
    # Refresh prior approved pages so their related links point internally
    # when a linked target migrates; manually authored pilot is unchanged.
    for record in entries:
        old_slug = record["id"]
        if old_slug == slug:
            continue
        source = root / "content" / "approved" / (old_slug + ".json")
        if source.is_file():
            prior = approved_article(root, old_slug)
            if prior.get("related_dzen_ids") and not catalog:
                catalog = catalog_entries(root)
            outputs[root / record["url"] / "index.html"] = render_article(prior, updated, catalog)

    if apply:
        for path, contents in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")
        print(f"Generated approved article and indexes: {BASE}/articles/{slug}/")
    else:
        print(f"DRY RUN only: {slug}; {len(outputs)} files would change, nothing written")
    return outputs


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("slug", help="Approved article slug (file content/approved/<slug>.json)")
    p.add_argument("--publish", action="store_true", help="Explicitly write approved site files")
    args = p.parse_args()
    try:
        publish(ROOT, args.slug, apply=args.publish)
    except (ValueError, OSError, KeyError) as exc:
        p.exit(1, f"Publication rejected: {exc}\n")


if __name__ == "__main__":
    main()
