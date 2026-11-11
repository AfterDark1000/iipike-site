"""Site-only entity tags on approved article header, never inside story text."""
import json
import re
from pathlib import Path
import unittest

from scripts.site_entities import (
    inject_article_entity_nav, load_registry, render_article_entity_nav,
)
from scripts.publish_approved_article import render_article

ROOT = Path(__file__).resolve().parents[1]
NAV = 'class="article-entity-links"'
CSS = '<link rel="stylesheet" href="../../assets/entities.css">'
COVER = '<figure class="cover">'


class ArticleEntityTagsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry(ROOT)
        cls.records = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
        cls.selected = {
            article_id for kind in ("companies", "products")
            for entry in cls.registry[kind] for article_id in entry["article_ids"]
        }

    def test_only_curated_articles_have_badges(self):
        # 195 existing archive assignments must survive, but the number
        # increases on each future editor-approved, tagged publication.
        self.assertGreaterEqual(len(self.selected), 195)
        for row in self.records:
            path = ROOT / row["url"] / "index.html"
            text = path.read_text(encoding="utf-8")
            expected = render_article_entity_nav(row["id"], self.registry)
            header = text.split(COVER, 1)[0]
            if row["id"] in self.selected:
                self.assertEqual(header.count(NAV), 1, row["id"])
                self.assertIn(expected, header, row["id"])
                self.assertEqual(header.count(CSS), 1, row["id"])
                self.assertNotIn(NAV, text.split(COVER, 1)[1], row["id"])
            else:
                self.assertEqual(expected, "", row["id"])
                self.assertNotIn(NAV, header, row["id"])

    def test_changes_are_reversible_header_only_and_idempotent(self):
        for article_id in self.selected:
            page = ROOT / "articles" / article_id / "index.html"
            after = page.read_text(encoding="utf-8")
            nav = render_article_entity_nav(article_id, self.registry)
            before = after.replace(nav, "", 1).replace("\n" + CSS, "", 1)
            rebuilt = inject_article_entity_nav(before, article_id, self.registry)
            self.assertEqual(rebuilt, after, article_id)
            self.assertEqual(inject_article_entity_nav(after, article_id, self.registry), after)
            self.assertEqual(after.split(COVER, 1)[1], before.split(COVER, 1)[1])
            self.assertEqual(after.split('<article class="article-text">', 1)[1],
                             before.split('<article class="article-text">', 1)[1])

    def test_disney_adobe_firefly_three_independent_destinations(self):
        ident = "disney-adobe-firefly-foundry-alliance-20261109"
        html = render_article_entity_nav(ident, self.registry)
        expected = (
            "../../entities/companies/adobe/",
            "../../entities/companies/disney/",
            "../../entities/products/firefly/",
        )
        for link in expected:
            self.assertIn('href="' + link + '"', html)
        self.assertEqual(html.count('<a href='), 3)
        self.assertNotIn("https://dzen.ru", html)

    def test_future_article_renderer_uses_same_site_only_chips(self):
        ident = "disney-adobe-firefly-foundry-alliance-20261109"
        source = ROOT / "content" / "approved" / (ident + ".json")
        self.assertTrue(source.is_file())
        data = json.loads(source.read_text(encoding="utf-8"))
        original = json.dumps(data, sort_keys=True, ensure_ascii=False)
        html = render_article(data, self.records)
        self.assertIn(render_article_entity_nav(ident, self.registry), html)
        self.assertEqual(html.count(CSS), 1)
        self.assertNotIn(NAV, html.split(COVER, 1)[1])
        self.assertEqual(original, json.dumps(data, sort_keys=True, ensure_ascii=False))

    def test_no_badges_for_unknown_article_and_bad_layout_fails_closed(self):
        unknown = "not-in-registry"
        self.assertEqual(render_article_entity_nav(unknown, self.registry), "")
        self.assertEqual(inject_article_entity_nav("untouched", unknown, self.registry), "untouched")
        known = next(iter(self.selected))
        with self.assertRaisesRegex(ValueError, "boundary"):
            inject_article_entity_nav("<html>broken</html>", known, self.registry)

    def test_chip_links_and_icons_are_local_and_exist(self):
        for slug in self.selected:
            nav = render_article_entity_nav(slug, self.registry)
            links = re.findall(r'href="(../../entities/(?:companies|products)/[a-z0-9-]+/)"', nav)
            icons = re.findall(r'src="(../../assets/entity-icons/[a-z0-9-]+\.svg)"', nav)
            self.assertGreaterEqual(len(links), 1)
            self.assertEqual(len(links), len(icons))
            for href in links:
                self.assertTrue((ROOT / "articles" / slug / href / "index.html").resolve().is_file())
            for icon in icons:
                self.assertTrue((ROOT / "articles" / slug / icon).resolve().is_file())


if __name__ == "__main__":
    unittest.main()
