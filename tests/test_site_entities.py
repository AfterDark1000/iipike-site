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
        self.assertEqual(len(self.registry["companies"]), 61)
        self.assertEqual(len(self.registry["products"]), 24)
        self.assertEqual(len(set(
            article for kind in ("companies", "products")
            for entity in self.registry[kind] for article in entity["article_ids"]
        )), 195)

    def test_generated_pages_are_current_indexable_and_canonical(self):
        pages = render_all_entities(self.records, ROOT)
        self.assertEqual(len(pages), 86)
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
        self.assertIn("Компании — 61", html)
        self.assertIn("Продукты — 24", html)
        self.assertEqual(html.count('class="topic-index-link entity-tile"'), 85)
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


if __name__ == "__main__":
    unittest.main()
