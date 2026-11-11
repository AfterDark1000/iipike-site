"""The entity taxonomy experiment must not touch the production publication flow."""
import json
from pathlib import Path
import unittest

from scripts.build_entity_pilot import render_all, validate, render_detail

ROOT = Path(__file__).resolve().parents[1]


class EntityPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "data/entity_pilot.json").read_text(encoding="utf-8"))
        cls.records = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))

    def test_registry_is_strict_and_references_only_published_articles(self):
        known = validate(self.manifest, self.records)
        self.assertGreater(len(known), 30)
        self.assertEqual(self.manifest["schema_version"], 1)
        self.assertEqual(len(self.manifest["companies"]), 6)
        self.assertEqual(len(self.manifest["products"]), 5)

    def test_dual_company_story_and_product_ownership_are_explicit(self):
        shared = "disney-adobe-firefly-foundry-alliance-20261109"
        companies = {x["key"]: x for x in self.manifest["companies"]}
        products = {x["key"]: x for x in self.manifest["products"]}
        self.assertIn(shared, companies["disney"]["article_ids"])
        self.assertIn(shared, companies["adobe"]["article_ids"])
        self.assertIn(shared, products["firefly"]["article_ids"])
        self.assertEqual(products["grok"]["company"], "xai")
        self.assertEqual(products["chatgpt"]["company"], "openai")

    def test_output_is_isolated_noindex_and_not_in_sitemap(self):
        pages = render_all(self.manifest, self.records, ROOT)
        self.assertEqual(len(pages), 12)
        sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
        self.assertNotIn("lab/entities", sitemap)
        for p, html in pages.items():
            self.assertTrue(str(p).startswith(str(ROOT / "lab/entities")))
            self.assertTrue(p.is_file())
            self.assertEqual(p.read_text(encoding="utf-8"), html)
            self.assertIn('content="noindex,nofollow,noarchive"', html)
            self.assertNotIn('rel="canonical"', html)
            self.assertNotIn('application/ld+json', html)
            self.assertNotIn('https://dzen.ru/a/', html)

    def test_invalid_id_and_path_fail_closed(self):
        import copy
        a = copy.deepcopy(self.manifest)
        a["companies"][0]["article_ids"].append("not-published")
        with self.assertRaisesRegex(ValueError, "Unpublished/unknown"):
            validate(a, self.records)
        b = copy.deepcopy(self.manifest)
        b["products"][0]["company"] = "unregistered"
        with self.assertRaisesRegex(ValueError, "registered company"):
            validate(b, self.records)

    def test_pilot_does_not_mark_incidental_mentions_as_company_news(self):
        companies = {x["key"]: set(x["article_ids"]) for x in self.manifest["companies"]}
        # Spacefast supports ChatGPT but is an Automattic story, not an OpenAI announcement.
        self.assertNotIn("automattic-spacefast-ai-agent-hosting-20261109", companies["openai"])
        # Claude appears in a Hacktron attack, but this is not an Anthropic announcement.
        self.assertNotIn("openai-hacktron-security-partnership-20261106", companies["anthropic"])

    def test_all_entity_icons_are_local_and_valid(self):
        import re
        pages = render_all(self.manifest, self.records, ROOT)
        all_keys = {entry["key"] for kind in ("companies", "products")
                    for entry in self.manifest[kind]}
        self.assertEqual(len(all_keys), 11)
        for key in all_keys:
            icon = ROOT / "lab" / "entities" / "icons" / (key + ".svg")
            self.assertTrue(icon.is_file(), str(icon))
            raw = icon.read_text(encoding="utf-8")
            self.assertTrue(raw.startswith("<svg"), key)
            self.assertNotIn("<script", raw)
            self.assertNotIn("http://", raw)
        for path, html in pages.items():
            self.assertIn("lab/entities/pilot-icons.css", html)
            refs = re.findall(r'src="([^"]+lab/entities/icons/[a-z]+\\.svg)"', html)
            self.assertTrue(refs, str(path))
            for href in refs:
                self.assertTrue((path.parent / href).resolve().is_file(), href)
            self.assertNotIn("unpkg.com", html)
            self.assertNotIn("cdn.jsdelivr.net", html)
        self.assertIn('class="topic-index-link entity-tile"',
                      pages[ROOT / "lab" / "entities" / "index.html"])

    def test_all_article_links_are_local_and_existing(self):
        pages = render_all(self.manifest, self.records, ROOT)
        known = {r["id"] for r in self.records}
        for html in pages.values():
            import re
            for ident in re.findall(r'href="../../../../articles/([^/]+)/"', html):
                self.assertIn(ident, known)
                self.assertTrue((ROOT / "articles" / ident / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
