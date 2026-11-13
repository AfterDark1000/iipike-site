"""Published rubric pages must use one UTC timeline, and remain generated assets."""
import json
from pathlib import Path
import re
import unittest

from scripts.site_rubrics import RUBRICS, render_page, publication_sort_key
from scripts.site_home import load_focus_items, update_home

ROOT = Path(__file__).resolve().parents[1]


class RubricOrderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))

    def test_four_published_rubric_pages_match_canonical_generator(self):
        for key in RUBRICS:
            with self.subTest(rubric=key):
                file = ROOT / "rubrics" / key / "index.html"
                stored = file.read_text(encoding="utf-8")
                expected = render_page(key, self.records)
                self.assertEqual(stored, expected,
                                 "Rubric page must be rebuilt by generator")

    def test_all_rubric_cards_sorted_by_real_publication_time(self):
        for key in RUBRICS:
            with self.subTest(rubric=key):
                html = (ROOT / "rubrics" / key / "index.html").read_text(
                    encoding="utf-8")
                got = re.findall(
                    r'<a class="archive-card" href="../../articles/([^/]+)/">',
                    html)
                expected = [
                    record["id"] for record in sorted(
                        (row for row in self.records
                         if row.get("rubric", "news") == key),
                        key=publication_sort_key, reverse=True)]
                self.assertEqual(got, expected)
                self.assertEqual(len(got), len(set(got)))

    def test_each_rubric_article_has_title_then_date_then_summary(self):
        for key in RUBRICS:
            with self.subTest(rubric=key):
                html = (ROOT / "rubrics" / key / "index.html").read_text(
                    encoding="utf-8")
                cards = re.findall(r'<a class="archive-card".*?</a>', html)
                for card in cards:
                    self.assertLess(card.index("<h3>"), card.index('<small class="date">'))
                    self.assertLess(card.index('<small class="date">'), card.index("<p>"))

    def test_editorial_selection_is_published_one_per_rubric(self):
        config = load_focus_items(ROOT)
        self.assertEqual(len(config), 4)
        by_id = {row["id"]: row for row in self.records}
        expected_keys = ["skynet", "news", "what-are-you-doing", "quotes"]
        self.assertEqual([by_id[entry["id"]]["rubric"] for entry in config],
                         expected_keys)
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertEqual(update_home(html, self.records, root=ROOT), html)
        for entry in config:
            self.assertIn('href="articles/' + entry["id"] + '/"', html)

    def test_same_day_order_uses_hour_not_slug(self):
        rows = [
            {"id": "z-morning", "published": "2026-11-13",
             "published_at_utc": "2026-11-13T06:15:00Z"},
            {"id": "a-evening", "published": "2026-11-13",
             "published_at_utc": "2026-11-13T18:15:00Z"},
            {"id": "yesterday", "published": "2026-11-12"},
        ]
        actual = sorted(rows, key=publication_sort_key, reverse=True)
        self.assertEqual([row["id"] for row in actual],
                         ["a-evening", "z-morning", "yesterday"])


if __name__ == "__main__":
    unittest.main()
