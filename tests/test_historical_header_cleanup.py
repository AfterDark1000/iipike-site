"""Original Dzen archive presentation cleanup: preserve all editorial provenance."""
import json
from pathlib import Path
import unittest

from scripts.historical_header_cleanup import cleanup_html, plan
from scripts.publish_approved_article import render_article

ROOT = Path(__file__).resolve().parents[1]
NEWS = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))


def fixture(slug):
    row = next(r for r in NEWS if r["id"] == slug)
    approved = json.loads(
        (ROOT / "content" / "approved" / (slug + ".json")).read_text(encoding="utf-8"))
    page = (ROOT / row["url"] / "index.html").read_text(encoding="utf-8")
    return row, approved, page


class HistoricalHeaderCleanupTests(unittest.TestCase):
    def test_original_nvidia_header_no_longer_repeats_the_opening(self):
        row, data, page = fixture("nvidia-opublikovala-arkhitekturu-s-apparatnym-stop-kranom-dlya-69bf0")
        result = cleanup_html(row, data, page)
        self.assertNotIn('<p class="summary">' + row["summary"], result)
        self.assertIn('<meta name="description" content="' + row["summary"], result)
        self.assertIn('<section class="article-body archive-body"><article class="article-text">', result)
        self.assertNotIn("Архивная публикация</h3>", result)
        self.assertNotIn("Версия в Дзене", result)
        self.assertIn('\"isBasedOn\": "' + row["dzen_url"] + '"', result)
        self.assertIn('<p class="lead">' + data["paragraphs"][0]["text"], result)
        self.assertEqual(result.split('<article class="article-text">', 1)[1],
                         page.split('<article class="article-text">', 1)[1])
        self.assertEqual(cleanup_html(row, data, result), result)

    def test_genuine_primary_source_remains_visible(self):
        row, data, page = fixture("codex-git-server")
        self.assertNotEqual(data["source_url"], data["dzen_url"])
        result = cleanup_html(row, data, page)
        self.assertNotIn("Версия в Дзене", result)
        self.assertNotIn('<p class="summary">', result.split('<figure class="cover">',1)[0])
        self.assertIn('<h3>Первоисточник</h3>', result)
        self.assertIn('href="' + data["source_url"] + '"', result)
        self.assertIn('\"isBasedOn\": "' + row["dzen_url"] + '"', result)
        self.assertEqual(cleanup_html(row, data, result), result)

    def test_reject_inconsistent_archive_provenance(self):
        row, data, page = fixture("codex-git-server")
        data["dzen_id"] = "fake"
        with self.assertRaisesRegex(ValueError, "Unmatched approved provenance"):
            cleanup_html(row, data, page)

    def test_publisher_keeps_new_approved_summary_visible(self):
        row, data, page = fixture("cnas-sovereign-agents-20261103")
        output = render_article(data, NEWS)
        self.assertIn('<p class="summary">' + data["summary"] + '</p>', output)
        self.assertIn('<h3>Первоисточник</h3>', output)
        self.assertNotIn("archive-body", output)
        self.assertIn('\"datePublished\": "' + data["published_at_utc"] + '"', output)

    def test_new_historical_rendering_keeps_original_dates_and_source(self):
        for slug in ("nvidia-opublikovala-arkhitekturu-s-apparatnym-stop-kranom-dlya-69bf0",
                     "codex-git-server"):
            with self.subTest(slug=slug):
                row, data, page = fixture(slug)
                output = render_article(data, NEWS)
                self.assertIn('\"isBasedOn\": "' + row["dzen_url"] + '"', output)
                self.assertIn('\"datePublished\": "' + data["published_at_utc"] + '"', output)
                self.assertIn('<p class="date">Опубликовано:', output)
                self.assertNotIn('<p class="summary">' + data["summary"], output)
                self.assertNotIn("Версия в Дзене", output)
                if data["source_url"] == data["dzen_url"]:
                    self.assertNotIn("Архивная публикация", output)
                    self.assertIn('class="article-body archive-body"', output)
                else:
                    self.assertIn('<h3>Первоисточник</h3>', output)

    def test_full_archive_plan_is_read_only_and_complete(self):
        historical, updates = plan(ROOT)
        self.assertEqual(historical, 218)
        self.assertLessEqual(len(updates), historical)
        self.assertGreaterEqual(len(updates), 0)
        for path, output in updates.items():
            self.assertIn('class="article-text"', output)
            self.assertIn('<link rel="canonical" ', output)


if __name__ == "__main__":
    unittest.main()
