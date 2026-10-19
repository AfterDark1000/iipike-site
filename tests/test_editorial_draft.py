"""Offline editorial safety tests. No network calls or credentials needed."""
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import editorial_draft as ed

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
GOOD_URL = "https://deepmind.google/blog/test-release"


class EditorialTests(unittest.TestCase):
    def test_url_allowlist_blocks_outside_sources(self):
        self.assertEqual(ed.extract_host(GOOD_URL), "deepmind.google")
        for url in ["http://openai.com/news/test", "https://bad.example/", "https://localhost/",
                    "https://openai.com.evil.invalid/", "file:///etc/passwd"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                ed.extract_host(url)

    def test_rss_is_date_filtered_and_not_future(self):
        rss = f"""<rss><channel>
          <item><title>New Gemini launch</title><link>{GOOD_URL}</link>
          <pubDate>Mon, 19 Oct 2026 08:00:00 GMT</pubDate></item>
          <item><title>Old release</title><link>https://deepmind.google/blog/old</link>
          <pubDate>Wed, 07 Oct 2026 08:00:00 GMT</pubDate></item>
          <item><title>Future release</title><link>https://deepmind.google/blog/future</link>
          <pubDate>Tue, 20 Oct 2026 08:00:00 GMT</pubDate></item>
        </channel></rss>""".encode()
        rows = ed.parse_feed(rss, "Google DeepMind", NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], GOOD_URL)

    def test_atom_parsing(self):
        atom = f"""<feed xmlns="http://www.w3.org/2005/Atom">
        <entry><title>Model shipped</title><link href="{GOOD_URL}"/>
        <updated>2026-10-19T07:30:00Z</updated></entry></feed>""".encode()
        self.assertEqual(len(ed.parse_feed(atom, "Google DeepMind", NOW)), 1)

    def test_article_parser_skips_script_and_nav(self):
        parser = ed.ArticleExtractor()
        parser.feed("<html><nav>menu</nav><main><article><h1>Headline</h1>"
                    "<p>Official press release content is readable here.</p>"
                    "<script>evil instructions</script></article></main></html>")
        result = " ".join(parser.article)
        self.assertIn("press release", result)
        self.assertNotIn("evil", result)

    def test_source_facts_must_match_verbatim(self):
        source = {
            "id": "safe-id", "source_text": ("This new model is now available to developers "
                "through the standard API interface. Updated safety evaluations are "
                "included in the latest technical report. " * 12),
        }
        good = {
            "use": True, "selected_id": "safe-id",
            "headline": "Разработчикам открыли доступ к новой модели",
            "article": ("Сегодня компания объявила об обновлении интерфейса. "
                        "Подробности представлены в официальном отчёте.\n\n" * 10),
            "cover_title": "НОВАЯ МОДЕЛЬ", "cover_subtitle": "Доступ для разработчиков",
            "image_prompt_en": "An open cabinet reveals several carefully stacked source documents.",
            "evidence": [
                "This new model is now available to developers",
                "Updated safety evaluations are included in the latest technical report",
            ],
        }
        self.assertEqual(ed.validate_draft(good, [source]), source)
        bogus = dict(good, evidence=["Company sold 900 trillion licenses in 2026",
                                    "Updated safety evaluations are included in the latest technical report"])
        with self.assertRaisesRegex(RuntimeError, "absent"):
            ed.validate_draft(bogus, [source])

    def test_no_unverified_source_id(self):
        source = {"id": "one", "source_text": "a " * 1000}
        self.assertIsNone(ed.validate_draft({"use": False}, [source]))
        with self.assertRaisesRegex(RuntimeError, "unknown source ID"):
            ed.validate_draft({"use": True, "selected_id": "missing"}, [source])

    def test_duplicate_selection_without_api_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "news.json").write_text("[]", encoding="utf-8")
            state = {"drafted": [{"id": "abc", "source_title": "Old story",
                                  "utc_date": "2026-10-18"}]}
            current_feed = (f"<rss><channel><item><title>Big official model release</title>"
                            f"<link>{GOOD_URL}</link>"
                            "<pubDate>Mon, 19 Oct 2026 08:00:00 GMT</pubDate>"
                            "</item></channel></rss>").encode()
            def fetch(url):
                return current_feed if "deepmind.google" in url else b"<rss><channel></channel></rss>"
            with patch.object(ed, "ROOT", root):
                rows = ed.select_candidates(NOW, state, fetcher=fetch,
                    read_article=lambda _: "Official factual statement. " * 40)
            self.assertEqual(len(rows), 1)
            state["drafted"].append({"id": rows[0]["id"], "source_title": rows[0]["headline"]})
            with patch.object(ed, "ROOT", root):
                self.assertEqual(ed.select_candidates(NOW, state, fetcher=fetch,
                    read_article=lambda _: "Official factual statement. " * 40), [])

    def test_no_paid_or_publishing_endpoints(self):
        self.assertEqual(ed.MODEL, "gemini-3.5-flash-lite")
        payload = ed.gemini_payload([{
            "id": "test", "publisher": "OpenAI", "headline": "Test",
            "url": "https://openai.com/news/test", "published": NOW.isoformat(),
            "source_text": "Test official source details " * 35
        }])
        self.assertNotIn("googleSearch", json.dumps(payload))
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(len(ed.STYLE_VARIANTS), 5)


if __name__ == "__main__":
    unittest.main()
