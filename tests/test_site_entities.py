"""Offline safety checks for the public company and product taxonomy."""
import json
import re
import unittest
from pathlib import Path

from scripts.site_entities import load_registry, render_all_entities, entity_urls
from scripts.site_entities import validate_public_registry

ROOT = Path(__file__).resolve().parents[1]


class PublicEntityCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry(ROOT)
        cls.records = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))

    def test_curated_registry_references_only_published_rows(self):
        validate_public_registry(self.registry, self.records)
        self.assertGreaterEqual(len(self.registry["companies"]), 61)
        self.assertGreaterEqual(len(self.registry["products"]), 24)
        self.assertGreaterEqual(len(set(
            article for kind in ("companies", "products")
            for entity in self.registry[kind] for article in entity["article_ids"]
        )), 195)

    def test_generated_pages_are_current_indexable_and_canonical(self):
        pages = render_all_entities(self.records, ROOT)
        self.assertEqual(sum(p.name == 'index.html' for p in pages), 1 + len(self.registry['companies']) + len(self.registry['products']))
        self.assertIn(ROOT / "entities/index.html", pages)
        for path, text in pages.items():
            self.assertTrue(path.is_file(), str(path))
            self.assertEqual(path.read_text(encoding="utf-8"), text, str(path))
            self.assertIn('rel="canonical" href="https://iipike.ru/entities/', text)
            self.assertNotIn('name="robots" content="noindex', text)
            self.assertNotIn("Экспериментальная страница", text)
            self.assertNotIn("https://dzen.ru/a/", text)
            self.assertIn('assets/entities.css', text)
            self.assertIn('assets/entity-icons/', text)
            self.assertNotIn("lab/entities/", text)
            self.assertNotIn('src="https://', text)

    def test_search_catalog_has_alphabetical_tiles(self):
        html = (ROOT / "entities/index.html").read_text(encoding="utf-8")
        self.assertIn('id="entity-filter"', html)
        self.assertIn('assets/entity-search.js', html)
        self.assertIn(f"Компании — {len(self.registry['companies'])}", html)
        self.assertIn(f"Продукты — {len(self.registry['products'])}", html)
        self.assertEqual(html.count('class="topic-index-link entity-tile"'), len(self.registry['companies']) + len(self.registry['products']))
        self.assertTrue((ROOT / "assets/entity-search.js").is_file())

    def test_all_icons_exist_and_are_local_svg(self):
        for kind in ("companies", "products"):
            for item in self.registry[kind]:
                img = ROOT / "assets/entity-icons" / (item["key"] + ".svg")
                self.assertTrue(img.is_file(), str(img))
                text = img.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("<svg"), str(img))
                self.assertNotIn("<script", text)
        self.assertTrue((ROOT / "assets/entities.css").is_file())

    def test_articles_are_real_and_links_stay_on_site(self):
        for row in self.records:
            self.assertTrue(row["url"].startswith("articles/"))
        for html in render_all_entities(self.records, ROOT).values():
            for slug in re.findall(r'href="../../../articles/([^/]+)/"', html):
                self.assertTrue((ROOT / "articles" / slug / "index.html").is_file())
        # Disney/Adobe is intentionally on both company pages.
        disney = "disney-adobe-firefly-foundry-alliance-20261109"
        for company in ("disney", "adobe"):
            p = ROOT / "entities" / "companies" / company / "index.html"
            self.assertIn(disney, p.read_text(encoding="utf-8"))

    def test_company_product_links_are_exact_reciprocal_and_local(self):
        for company in self.registry["companies"]:
            key = company["key"]
            path = ROOT / "entities" / "companies" / key / "index.html"
            html = path.read_text(encoding="utf-8")
            owned = sorted((p for p in self.registry["products"] if p["company"] == key),
                           key=lambda p: (p["name"].casefold(), p["key"]))
            actual = re.findall(r'class="entity-product-link" href="../../products/([a-z0-9-]+)/"', html)
            self.assertEqual(actual, [p["key"] for p in owned], key)
            self.assertEqual(html.count('id="company-products-title"'), int(bool(owned)), key)
            for product in owned:
                page = ROOT / "entities" / "products" / product["key"] / "index.html"
                self.assertTrue(page.is_file())
                reverse = page.read_text(encoding="utf-8")
                self.assertIn('href="../../companies/' + key + '/"', reverse)
                self.assertNotIn('id="company-products-title"', reverse)
        openai = (ROOT / "entities/companies/openai/index.html").read_text(encoding="utf-8")
        self.assertIn('href="../../products/chatgpt/"', openai)
        self.assertNotIn('href="../../products/claude/"', openai)

    def test_navigation_and_sitemap(self):
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        archive = (ROOT / "articles/index.html").read_text(encoding="utf-8")
        sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn('href="entities/">Компании', home)
        self.assertIn('href="../entities/">Компании и продукты', archive)
        for url in entity_urls(self.registry):
            self.assertEqual(sitemap.count("<loc>" + url + "</loc>"), 1)
        self.assertNotIn("lab/entities/", sitemap)
        lab = (ROOT / "lab/entities/index.html").read_text(encoding="utf-8")
        self.assertIn('content="noindex,nofollow,noarchive"', lab)


    def test_detail_pages_keep_curated_membership_and_real_dates(self):
        from scripts.site_rubrics import publication_sort_key, publication_label
        from itertools import groupby
        by_id = {r["id"]: r for r in self.records}
        for kind in ("companies", "products"):
            for entry in self.registry[kind]:
                from scripts.site_rubrics import listing_markup, listing_days
                html = listing_markup(ROOT / "entities" / kind / entry["key"] / "index.html")
                records = sorted((by_id[x] for x in entry["article_ids"]), key=publication_sort_key, reverse=True)
                self.assertEqual(re.findall(r'<a class="archive-card" href="../../../articles/([^/]+)/">', html),
                                 [r["id"] for r in records])
                labels = [publication_label(r) for r in records]
                self.assertEqual(re.findall(r'<h2 class="rubric-day-title">(.*?)</h2>', html),
                                 listing_days(labels))
                self.assertEqual(re.findall(r'<span class="rubric-time" aria-label="([^"]+)">([^<]*)</span>', html),
                                 [(x, x.partition(" · ")[2]) for x in labels])
                self.assertIn('class="home-v1 rubric-r2 entity-r2"', html)
                self.assertIn(f"Материалов: {len(records)}", html)


if __name__ == "__main__":
    unittest.main()
