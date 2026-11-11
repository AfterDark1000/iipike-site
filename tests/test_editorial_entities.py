"""Only editor-selected, registered company/product IDs may enter the public archive."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from scripts.site_entities import (append_editor_entities,
                                   load_registry, validate_editor_entities,
                                   validate_public_registry)

ROOT = Path(__file__).resolve().parents[1]


class EditorEntityMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry()
        cls.records = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))

    def test_known_company_product_and_parent_link(self):
        self.assertEqual(validate_editor_entities(self.registry, ["adobe", "disney"], ["firefly"]),
                         (["adobe", "disney"], ["firefly"]))
        self.assertEqual(validate_editor_entities(self.registry, [], ["grok"]),
                         (["xai"], ["grok"]))
        self.assertEqual(validate_editor_entities(self.registry, [], []), ([], []))
        self.assertEqual(validate_editor_entities(self.registry), ([], []))

    def test_unknown_duplicates_wrong_shapes_and_excess_fail_closed(self):
        for companies, products in (
            (["nobody-registered"], []), ([], ["not-a-real-product"]),
            (["openai", "openai"], []), ([], ["grok", "grok"]),
            ("openai", []), ([], "grok"),
            (None, ["grok", "claude", "gemini", "firefly", "chatgpt"]),
        ):
            with self.subTest(companies=companies, products=products):
                with self.assertRaises(ValueError):
                    validate_editor_entities(self.registry, companies, products)

    def test_copy_on_write_never_changes_historical_assignments(self):
        before = deepcopy(self.registry)
        slug = "new-reviewed-article-20261111"
        updated = append_editor_entities(self.registry, slug, ["disney"], ["firefly"])
        self.assertEqual(before, self.registry)
        companies = {row["key"]: row["article_ids"] for row in updated["companies"]}
        products = {row["key"]: row["article_ids"] for row in updated["products"]}
        self.assertIn(slug, companies["adobe"])
        self.assertIn(slug, companies["disney"])
        self.assertIn(slug, products["firefly"])
        self.assertNotIn(slug, companies["google"])
        self.assertEqual(companies["google"],
                         next(row["article_ids"] for row in before["companies"]
                              if row["key"] == "google"))

    def test_existing_article_cannot_be_appended_twice(self):
        with self.assertRaisesRegex(ValueError, "already assigned"):
            append_editor_entities(self.registry, "google-tpu-8tx-8i-max-20261109",
                                   ["google"], ["gemini"])

    def test_new_story_with_explicit_entities_passes_registry_validation(self):
        row = deepcopy(self.records[0])
        row["id"] = "new-reviewed-article-20261111"
        row["url"] = "articles/new-reviewed-article-20261111/"
        row["companies"], row["products"] = ["adobe", "disney"], ["firefly"]
        updated = append_editor_entities(self.registry, row["id"],
                                         row["companies"], row["products"])
        known = validate_public_registry(updated, self.records + [row])
        self.assertIn(row["id"], known)


if __name__ == "__main__":
    unittest.main()
