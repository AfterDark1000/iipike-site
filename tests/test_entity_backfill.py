"""One-time entity backfill changes article headers, never editorial text."""
import json
from pathlib import Path
import unittest

from scripts.backfill_article_entities import plan, update_header, COVER, BODY
from scripts.site_entities import load_registry, render_article_entity_nav

ROOT = Path(__file__).resolve().parents[1]


class HeaderBackfillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry(ROOT)
        cls.pilot = json.loads((ROOT / "data/entity_pilot.json").read_text(encoding="utf-8"))

    def test_all_headers_are_updated_only_for_curated_articles(self):
        selected, changes = plan(ROOT)
        self.assertEqual(len(selected), 195)
        self.assertEqual(changes, {})

    def test_existing_brand_tags_can_expand_but_body_stays_exact(self):
        ident = "google-tpu-8tx-8i-max-20261109"
        page = (ROOT / "articles" / ident / "index.html").read_text(encoding="utf-8")
        self.assertEqual(update_header(page, ident, self.registry, self.pilot), page)

    def test_unknown_article_never_gets_a_guessed_entity(self):
        ident = "ai-agents-cent-spending-limit"
        self.assertEqual(render_article_entity_nav(ident, self.registry), "")
        page = (ROOT / "articles" / ident / "index.html").read_text(encoding="utf-8")
        self.assertEqual(update_header(page, ident, self.registry, self.pilot), page)

    def test_existing_header_can_only_have_known_old_markup(self):
        ident = "google-tpu-8tx-8i-max-20261109"
        page = (ROOT / "articles" / ident / "index.html").read_text(encoding="utf-8")
        malformed = page.replace('class="article-entity-links"', 'class="article-entity-links" data-tampered="1"', 1)
        with self.assertRaises(ValueError):
            update_header(malformed, ident, self.registry, self.pilot)

    def test_new_tags_preserve_html_after_cover(self):
        ident = "microsoft-copilot-twenty-models"
        page = (ROOT / "articles" / ident / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="article-entity-links"', page)
        self.assertIn(COVER, page)
        self.assertIn(BODY, page)
        self.assertEqual(update_header(page, ident, self.registry, self.pilot), page)


if __name__ == "__main__":
    unittest.main()
