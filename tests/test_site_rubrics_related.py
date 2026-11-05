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
        cls.trusted = next(x for x in cls.catalog.values()
                           if verified(x) and x.get("published_at_utc"))
        # Once the historical backlog is fully recovered, no real unverified
        # catalog entry should remain. Use an explicit invalid fixture.
        synthetic_id = "ffffffffffffffffffffffff"
        assert synthetic_id not in cls.catalog
        cls.untrusted = dict(cls.trusted, dzen_id=synthetic_id,
                             title="НЕПРОВЕРЕННЫЙ ТЕСТОВЫЙ ИСТОЧНИК",
                             title_evidence="unavailable",
                             url_evidence="derived_from_12_byte_id")
        cls.catalog = {**cls.catalog, synthetic_id: cls.untrusted}

    def test_existing_catalog_not_recreated_or_all_published(self):
        self.assertGreaterEqual(len(self.catalog), 200)
        self.assertGreaterEqual(sum(verified(x) for x in self.catalog.values()), 150)
        self.assertFalse(verified(self.untrusted))
        with self.assertRaisesRegex(ValueError, "Unverified"):
            validate_reference(self.untrusted["dzen_id"], self.catalog)
        pilot = next(row for row in self.records if row["id"] == "google-search-ai-links")
        self.assertFalse(pilot.get("dzen_id"), "Pilot article must not inherit a fake Dzen ID")

    def test_canonical_four_rubrics_and_valid_pages(self):
        self.assertEqual(list(RUBRICS), ["news", "skynet", "what-are-you-doing", "quotes"])
        self.assertEqual(populated(self.records), list(RUBRICS))
        expected = render_all(self.records, ROOT)
        self.assertEqual(len(expected), 4)
        for path, markup in expected.items():
            self.assertEqual(path.read_text(encoding="utf-8"), markup, str(path))
            self.assertIn('rel="canonical" href="https://iipike.ru/rubrics/', markup)
            self.assertIn("Хроники Пикирующего ИИ", markup)
            if path.parent.name in populated(self.records):
                self.assertNotIn('name="robots" content="noindex', markup)
            else:
                self.assertIn('name="robots" content="noindex, follow"', markup)
            if path.parent.name == "news":
                self.assertIn("google-search-ai-links", markup)

    def test_mobile_archive_cards_have_full_width_covers_and_clamped_teasers(self):
        stylesheet = (ROOT / "assets" / "site.css").read_text(encoding="utf-8")
        # The last, mobile-specific declaration overrides an older two-column
        # card rule that made text unreadable beside 116px thumbnail images.
        media = stylesheet.rsplit("@media(max-width:680px)", 1)[-1]
        self.assertIn(".archive-card{", media)
        self.assertIn("grid-template-columns:minmax(0,1fr)", media)
        self.assertIn("aspect-ratio:16/9", media)
        self.assertIn(".archive-card p{", media)
        self.assertIn("-webkit-line-clamp:3", media)
        self.assertIn(".archive-card > span:last-child{display:none;}", media)

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

    def test_related_links_prefer_site_first_counterpart_too(self):
        item = self.trusted
        records = [{"id": "fresh-site-first", "url": "articles/fresh-site-first/",
                    "title": "Сначала сайт",
                    "site_first_dzen_id": item["dzen_id"],
                    "site_first_dzen_url": item["dzen_url"]}]
        output = render_links([item["dzen_id"]], records, self.catalog)
        self.assertIn('../../articles/fresh-site-first/', output)
        self.assertNotIn('href="' + item["dzen_url"], output)

    def test_readonly_suggestions_do_not_return_unverified(self):
        suggested = suggest({"title": self.trusted["title"],
                             "summary": self.trusted.get("excerpt") or self.trusted["title"]},
                            self.catalog)
        for _, _, ident in suggested:
            self.assertTrue(verified(self.catalog[ident]))

    def test_original_dzen_date_is_the_single_visible_publication_date(self):
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
            shutil.copy(ROOT / "index.html", root / "index.html")
            shutil.copy(ROOT / "data" / "editorial_full_catalog_snapshot.json",
                        root / "data" / "editorial_full_catalog_snapshot.json")
            original = self.trusted["published_at_utc"]
            self.assertTrue(original)
            original = original.replace("+00:00", "Z")
            from zoneinfo import ZoneInfo
            original_day = dt.datetime.fromisoformat(original.replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Yekaterinburg")).date().isoformat()
            record = {
                "slug": "migrated-article", "status": "approved",
                "approved_by": "editor", "approved_at": "2026-11-04",
                "rubric": "skynet", "section": "РАЗБОР",
                "title": self.trusted["title"],
                "summary": "Отредактированный и проверенный материал.",
                "published": original_day,
                "published_at_utc": original,
                "event_date": "2026-11-03",
                "source_url": "https://example.org/story",
                "source_title": "Первичный источник",
                "cover": "assets/cover.svg",
                "dzen_id": self.trusted["dzen_id"],
                "dzen_url": self.trusted["dzen_url"],
                "related_dzen_ids": [],
                "paragraphs": [{"type":"lead", "text":"Вступление."},
                               {"type":"p", "text":"Текст статьи."}]
            }
            source = root / "content" / "approved" / "migrated-article.json"
            source.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            outputs = pub.publish(root, "migrated-article", apply=False)
            html = outputs[root / "articles" / "migrated-article" / "index.html"]
            self.assertIn('article:published_time" content="' + original + '"', html)
            self.assertIn("Опубликовано:", html)
            self.assertNotIn("На сайте:", html)
            self.assertNotIn("Первоначально опубликовано в Дзене:", html)
            self.assertNotIn("Версия в Дзене", html)
            self.assertNotIn('<p class="summary">', html.split('<figure class="cover">', 1)[0])
            self.assertIn('<h3>Первоисточник</h3>', html)
            self.assertNotIn("article:modified_time", html)
            self.assertIn('"datePublished": "' + original + '"', html)
            self.assertNotIn('"dateModified"', html)
            self.assertIn(self.trusted["dzen_url"], html)
            records = json.loads(outputs[root / "news.json"])
            self.assertEqual(records[-1]["published"], original_day)
            self.assertEqual(records[-1]["published_at_utc"], original)
            self.assertNotIn("original_dzen_published_at_utc", records[-1])
            self.assertIn("https://iipike.ru/rubrics/skynet/",
                          outputs[root / "sitemap.xml"])
            self.assertFalse((root / "articles").exists())

    def test_reject_lying_about_source_date(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "publisher", ROOT / "scripts" / "publish_approved_article.py")
        pub = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pub)
        self.assertIn("Publication date must match verified original Dzen publication",
                      Path(pub.__file__).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
