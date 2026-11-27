"""Show real local publication minutes and do not invent time for historical days."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.site_rubrics import publication_label, render_page
from scripts.backfill_publication_times import output_map

ROOT = Path(__file__).resolve().parents[1]


class PublicationTimesTests(unittest.TestCase):
    def test_new_article_uses_editorial_time_zone(self):
        row = {"id": "test-timed-story", "published": "2026-11-19",
               "published_at_utc": "2026-11-19T07:30:00Z"}
        self.assertEqual(publication_label(row), "19 ноября 2026 · 12:30")
        row["published_at_utc"] = "2026-11-18T22:30:00Z"
        self.assertEqual(publication_label(row), "19 ноября 2026 · 03:30")

    def test_day_only_history_has_no_imagined_minute(self):
        row = {"published": "2026-10-19", "publication_date_precision": "day",
               "published_at_utc": "2026-10-19T00:00:00Z"}
        self.assertEqual(publication_label(row), "19 октября 2026")
        self.assertEqual(publication_label({"published": "2026-10-19"}), "19 октября 2026")

    def test_rubric_cards_use_same_time_format(self):
        row = {"id": "timed", "title": "Важная новая статья", "summary": "Текст",
               "cover": "assets/example.webp", "url": "articles/timed/",
               "published": "2026-11-19",
               "published_at_utc": "2026-11-19T07:30:00Z", "rubric": "news"}
        html = render_page("news", [row])
        self.assertIn('<h2 class="rubric-day-title">19 ноября 2026</h2>', html)
        self.assertIn('<span class="rubric-time" aria-label="19 ноября 2026 · 12:30">12:30</span>', html)
        day_only = dict(row, publication_date_precision="day")
        self.assertIn('<span class="rubric-time" aria-label="19 ноября 2026"></span>', render_page("news", [day_only]))

    def test_existing_article_metadata_only_and_idempotent_backfill(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            row = {"id": "some-article", "title": "Опубликованная статья",
                   "summary": "Проверенная запись", "cover": "assets/sample.webp",
                   "url": "articles/some-article/", "published": "2026-11-19",
                   "published_at_utc": "2026-11-19T07:30:00Z", "rubric": "news"}
            (root / "news.json").write_text(json.dumps([row]), encoding="utf-8")
            shutil.copyfile(ROOT / "index.html", root / "index.html")
            dest = root / "articles/some-article/index.html"
            dest.parent.mkdir(parents=True)
            dest.write_text(
                '<div><p class="date">Опубликовано: 19 ноября 2026</p>'
                '<p>Не менять текст статьи!</p></div>', encoding="utf-8")
            outputs, report = output_map(root)
            self.assertEqual(report["article_dates_updated"], 1)
            self.assertIn("19 ноября 2026 · 12:30", outputs[dest])
            self.assertIn("Не менять текст статьи!", outputs[dest])
            for path, content in outputs.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            outputs2, report2 = output_map(root)
            self.assertEqual(report2["article_dates_updated"], 0)
            self.assertNotIn(dest, outputs2)
            self.assertEqual(dest.read_text(encoding="utf-8"), outputs[dest])


if __name__ == "__main__":
    unittest.main()
