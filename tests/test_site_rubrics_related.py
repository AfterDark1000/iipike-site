"""Offline regression tests for rubrics, historical catalog provenance and migration dates."""
import datetime as dt
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.site_rubrics import RUBRICS, populated, render_all
from scripts.site_related import (catalog_entries, verified, validate_reference,
                                  validate_links, render_links, suggest)

ROOT = Path(__file__).resolve().parents[1]


class RubricAndArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = catalog_entries(ROOT)
        cls.records = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
        cls.trusted = next(x for x in cls.catalog.values() if verified(x))
        cls.untrusted = next(x for x in cls.catalog.values() if not verified(x))

    def test_existing_catalog_not_recreated_or_all_published(self):
        self.assertGreaterEqual(len(self.catalog), 200)
        self.assertGreaterEqual(sum(verified(x) for x in self.catalog.values()), 150)
        self.assertFalse(verified(self.untrusted))
        with self.assertRaisesRegex(ValueError, "Unverified"):
            validate_reference(self.untrusted["dzen_id"], self.catalog)
        self.assertFalse(any(row.get("dzen_id") for row in self.records),
                         "Pilot article must not inherit a fake Dzen ID")

    def test_canonical_four_rubrics_and_valid_pages(self):
        self.assertEqual(list(RUBRICS), ["news", "skynet", "what-are-you-doing", "quotes"])
        self.assertEqual(populated(self.records), ["news"])
        expected = render_all(self.records, ROOT)
        self.assertEqual(len(expected), 4)
        for path, markup in expected.items():
            self.assertEqual(path.read_text(encoding="utf-8"), markup, str(path))
            self.assertIn('rel="canonical" href="https://iipike.ru/rubrics/', markup)
            self.assertIn("Хроники Пикирующего ИИ", markup)
            if "news/" in str(path):
                self.assertNotIn('name="robots" content="noindex', markup)
                self.assertIn("google-search-ai-links", markup)
            else:
                self.assertIn('name="robots" content="noindex, follow"', markup)

    def test_unsafe_related_and_self_links_refused(self):
        current = self.trusted["dzen_id"]
        with self.assertRaisesRegex(ValueError, "itself"):
            validate_links([current], self.catalog, current=current)
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_links([current, current], self.catalog)
        with self.assertRaisesRegex(ValueError, "Unverified"):
            validate_links([self.untrusted["dzen_id"]], self.catalog)
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_links([{"bad": "id"}], self.catalog)

    def test_link_to_site_preferred_over_original_dzen(self):
        current = self.trusted
        external = render_links([current["dzen_id"]], [], self.catalog)
        self.assertIn(current["dzen_url"], external)
        self.assertIn("В Дзене", external)
        records = [{"dzen_id": current["dzen_id"],
                    "url": "articles/migrated-story/", "title": "На своём сайте"}]
        internal = render_links([current["dzen_id"]], records, self.catalog)
        self.assertIn('../../articles/migrated-story/', internal)
        self.assertIn("На своём сайте", internal)
        self.assertIn("На сайте", internal)
        self.assertNotIn('href="' + current["dzen_url"], internal)

    def test_readonly_suggestions_do_not_return_unverified(self):
        suggested = suggest({"title": self.trusted["title"],
                             "summary": self.trusted.get("excerpt") or self.trusted["title"]},
                            self.catalog)
        for _, _, ident in suggested:
            self.assertTrue(verified(self.catalog[ident]))

    def test_same_site_date_and_original_date_remain_distinct(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "publisher", ROOT / "scripts" / "publish_approved_article.py")
        pub = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pub)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "content" / "approved").mkdir(parents=True)
            (root / "assets").mkdir()
            (root / "data").mkdir()
            (root / "assets" / "cover.svg").write_text("<svg/>", encoding="utf-8")
            shutil.copy(ROOT / "news.json", root / "news.json")
            shutil.copy(ROOT / "feed.xml", root / "feed.xml")
            shutil.copy(ROOT / "data" / "editorial_full_catalog_snapshot.json",
                        root / "data" / "editorial_full_catalog_snapshot.json")
            original = self.trusted["published_at_utc"]
            self.assertTrue(original)
            original = original.replace("+00:00", "Z")
            record = {
                "slug": "migrated-article", "status": "approved",
                "approved_by": "editor", "approved_at": "2026-11-04",
                "rubric": "skynet", "section": "РАЗБОР",
                "title": self.trusted["title"],
                "summary": "Отредактированный и проверенный материал.",
                "published": "2026-11-04",
                "published_at_utc": "2026-11-04T12:00:00Z",
                "event_date": "2026-11-03",
                "source_url": "https://example.org/story",
                "source_title": "Первичный источник",
                "cover": "assets/cover.svg",
                "dzen_id": self.trusted["dzen_id"],
                "dzen_url": self.trusted["dzen_url"],
                "original_dzen_published_at_utc": original,
                "related_dzen_ids": [],
                "paragraphs": [{"type":"lead", "text":"Вступление."},
                               {"type":"p", "text":"Текст статьи."}]
            }
            source = root / "content" / "approved" / "migrated-article.json"
            source.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            outputs = pub.publish(root, "migrated-article", apply=False)
            html = outputs[root / "articles" / "migrated-article" / "index.html"]
            self.assertIn('article:published_time" content="2026-11-04T12:00:00Z"', html)
            self.assertIn("На сайте: 4 ноября 2026", html)
            self.assertIn("Первоначально опубликовано в Дзене:", html)
            self.assertIn(self.trusted["dzen_url"], html)
            records = json.loads(outputs[root / "news.json"])
            self.assertEqual(records[-1]["published"], "2026-11-04")
            self.assertEqual(records[-1]["original_dzen_published_at_utc"], original)
            self.assertIn("https://iipike.ru/rubrics/skynet/",
                          outputs[root / "sitemap.xml"])
            self.assertFalse((root / "articles").exists())

    def test_reject_lying_about_source_date(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "publisher", ROOT / "scripts" / "publish_approved_article.py")
        pub = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pub)
        self.assertIn("Site publication may not predate original Dzen publication",
                      Path(pub.__file__).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
