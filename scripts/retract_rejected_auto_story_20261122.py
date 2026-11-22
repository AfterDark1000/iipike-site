#!/usr/bin/env python3
"""One-time chief-editor retraction of a rejected, already-published auto draft.

This does not publish any new story. It removes precisely one publication from
the site and returns its ORIGINAL raw news item to a human-editor hot queue.
Old human decisions and machine receipts remain as immutable audit evidence.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import site_news_pool, editorial_routing
from scripts.publish_approved_article import render_catalog, render_feed
from scripts.build_dzen_rss import render as render_dzen_rss
from scripts.build_vk_rss import export as export_vk
from scripts.build_sitemap import render as render_sitemap
from scripts.site_home import update_home
from scripts.site_rubrics import render_all
from scripts.site_topics import render_all_topics
from scripts.site_entities import render_all_entities, validate_public_registry

ARTICLE = "ii-kompanii-nanimayut-byvshikh-razvedchikov-za-za-8e599f8fd3fc906d"
POOL_ID = "n-8e599f8fd3fc906d"
REQUEST = ROOT / "data/site_retractions/requests/retract-20261122-counterintelligence.json"
RECEIPT = ROOT / "data/site_retractions/receipts/retract-20261122-counterintelligence.json"
EXPECTED_PUBLISHED_SOURCE = (
    "https://www.reuters.com/legal/litigation/"
    "help-wanted-ai-firms-court-ex-spies-nvidia-drama-spotlights-security-risks-2026-11-12/"
)
EXPECTED_ORIGINAL_SOURCE = (
    "https://www.marketscreener.com/news/"
    "help-wanted-ai-firms-court-ex-spies-as-nvidia-drama-spotlights-security-risks-ce785ed8df8df323"
)
NOTE = (
    "22.11.2026: главред отклонил качество опубликованной версии автономного редактора. "
    "Материал снят с сайта и возвращён в горячую очередь на НОВУЮ РУЧНУЮ редактуру. "
    "Не принимать прежний автодрафт и не отдавать этому же автономному редактору. "
    "Историческая заявка: auto-20261120-0252-ordinary-005.json. "
    "Первоисточник для перепроверки: " + EXPECTED_PUBLISHED_SOURCE
)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def store(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def remove_file(path, *, required=False):
    if path.is_symlink():
        raise ValueError("Refusing to remove symlink: " + str(path))
    if required and not path.is_file():
        raise ValueError("Expected published artifact missing: " + str(path))
    if path.is_file():
        path.unlink()


def main():
    if RECEIPT.exists():
        raise ValueError("Retraction was already completed; refusing to repeat")
    request = load(REQUEST)
    if request != {
        "schema_version": 1,
        "action": "retract_publication_and_return_to_manual_pool",
        "article_id": ARTICLE,
        "pool_id": POOL_ID,
        "authorized_by": "AfterDark1000",
    }:
        raise ValueError("Unapproved or malformed single-story retraction request")
    records = load(ROOT / "news.json")
    matching = [r for r in records if r.get("id") == ARTICLE]
    if len(matching) != 1:
        raise ValueError("Expected exactly one published target article")
    if matching[0].get("source_url") != EXPECTED_PUBLISHED_SOURCE:
        raise ValueError("Published source changed; refusing stale retraction")
    if matching[0].get("url") != "articles/" + ARTICLE + "/":
        raise ValueError("Published article URL changed")
    page = ROOT / "articles" / ARTICLE / "index.html"
    approved = ROOT / "content" / "approved" / (ARTICLE + ".json")
    if not page.is_file() or not approved.is_file():
        raise ValueError("Missing original published page or approved source")
    if load(approved).get("slug") != ARTICLE:
        raise ValueError("Approved source identity changed")

    pool = load(ROOT / "data/site_news_pool.json")
    site_news_pool.validate(pool)
    item = next((x for x in pool["items"] if x["id"] == POOL_ID), None)
    if not item or item["sequence"] != 58 or item["status"] != "in_review":
        raise ValueError("Raw pool candidate is no longer the expected in-review item")
    if item["source_url"] != EXPECTED_ORIGINAL_SOURCE:
        raise ValueError("Original candidate source changed")
    if ("AUTO_EDITOR claim=auto-20261120-0252-ordinary-005.json; "
            "article_id=" + ARTICLE) not in item["note"]:
        raise ValueError("Cannot prove exact autonomous claim ownership")
    updated_pool, _ = site_news_pool.transition(pool, POOL_ID, "return", note=NOTE)
    moved = next(x for x in updated_pool["items"] if x["id"] == POOL_ID)
    moved["priority"] = "high"
    site_news_pool.validate(updated_pool)

    routes = load(ROOT / "data/editorial_routing.json")
    route = next((x for x in routes["items"] if x["pool_id"] == POOL_ID), None)
    if not route or route.get("sequence") != 58 or route.get("lane") != "long":
        raise ValueError("Expected route for item 58 is missing or altered")
    route["lane"] = "long"
    route["decision"] = "hot"
    editorial_routing.validate_document(routes, updated_pool, require_all=False)

    updated = [row for row in records if row["id"] != ARTICLE]
    registry = load(ROOT / "data/entity_registry.json")
    assigned = 0
    for kind in ("companies", "products"):
        for entity in registry[kind]:
            if ARTICLE in entity["article_ids"]:
                entity["article_ids"].remove(ARTICLE)
                assigned += 1
    if assigned != 3:
        raise ValueError("Expected three company registry memberships; got " + str(assigned))
    validate_public_registry(registry, updated)

    # Protect against silent broken links from later published article pages.
    other_pages = [
        str(p.relative_to(ROOT)) for p in (ROOT / "articles").glob("*/index.html")
        if p != page and ARTICLE in p.read_text(encoding="utf-8")
    ]
    if other_pages:
        raise ValueError("Other published pages reference withdrawn article: " + str(other_pages))

    old_feed = (ROOT / "feed.xml").read_text(encoding="utf-8")
    old_home = (ROOT / "index.html").read_text(encoding="utf-8")

    # Retire public artifacts, including copies of the approved editorial handoff.
    remove_file(page, required=True)
    remove_file(approved, required=True)
    for rel in (
        f"assets/editorial/{ARTICLE}.webp",
        f"assets/vk/{ARTICLE}.jpg",
        f"editorial_inbox/stories/{ARTICLE}.json",
        f"editorial_inbox/covers/{ARTICLE}.webp",
    ):
        remove_file(ROOT / rel)

    store(ROOT / "news.json", updated)
    store(ROOT / "data/site_news_pool.json", updated_pool)
    store(ROOT / "data/editorial_routing.json", routes)
    store(ROOT / "data/entity_registry.json", registry)

    (ROOT / "articles/index.html").write_text(render_catalog(updated), encoding="utf-8")
    (ROOT / "feed.xml").write_text(render_feed(updated, old_feed), encoding="utf-8")
    (ROOT / "dzen-rss.xml").write_text(render_dzen_rss(ROOT, updated), encoding="utf-8")
    (ROOT / "index.html").write_text(
        update_home(old_home, updated, root=ROOT), encoding="utf-8"
    )
    for generator in (render_all, render_all_topics):
        for dest, html in generator(updated, ROOT).items():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(html, encoding="utf-8")
    for dest, html in render_all_entities(updated, ROOT, registry=registry).items():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html, encoding="utf-8")
    (ROOT / "sitemap.xml").write_text(render_sitemap(), encoding="utf-8")
    export_vk(ROOT)

    # No public generated index or feed may still refer to the withdrawn ID.
    public_paths = [
        ROOT / "index.html", ROOT / "articles/index.html",
        ROOT / "feed.xml", ROOT / "dzen-rss.xml", ROOT / "vk-rss.xml",
        ROOT / "sitemap.xml",
    ]
    for folder in ("rubrics", "topics", "entities"):
        public_paths.extend((ROOT / folder).rglob("index.html"))
    for dest in public_paths:
        if ARTICLE in dest.read_text(encoding="utf-8"):
            raise ValueError("Stale public reference remains: " + str(dest))

    store(RECEIPT, {
        "schema_version": 1,
        "action": "retract_publication_and_return_to_manual_pool",
        "article_id": ARTICLE,
        "pool_id": POOL_ID,
        "sequence": 58,
        "status": "retracted_and_queued_for_manual_editor",
        "historic_claim": "auto-20261120-0252-ordinary-005.json",
        "note": "Chief editor rejected the autonomous article; no automated reapproval.",
    })
    print("RETRACTION_PREPARED: " + ARTICLE)
    print("ORIGINAL_POOL_RETURNED: #58 high / long / hot, manual editor only")
    print("PUBLICATION_CATALOG_COUNT: " + str(len(updated)))


if __name__ == "__main__":
    main()
