"""Security and coverage tests of broad AI discovery; offline, no subscriptions."""
import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import editorial_sources as src
import editorial_draft as ed

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 20, 10, 0, tzinfo=UTC)


class CoverageTests(unittest.TestCase):
    def test_broad_multi_vendor_catalog(self):
        self.assertGreaterEqual(len(src.SOURCES), 18)
        names = " ".join(row[0] for row in src.SOURCES)
        for company in ("OpenAI", "Microsoft", "NVIDIA", "Amazon", "Hugging Face",
                        "Google", "Ollama"):
            self.assertIn(company, names)

    def test_primary_source_allowlist(self):
        for link in (
            "https://www.anthropic.com/news/announcing-something",
            "https://blogs.nvidia.com/blog/new-ai-video-model/",
            "https://www.minimax.io/news/new-release",
            "https://openai.com/index/new-model",
            "https://github.com/ollama/ollama/releases/tag/v1.0.0",
        ):
            with self.subTest(link=link):
                self.assertTrue(src.is_official_article(link))
        for link in (
            "https://github.com/random-user/malicious-repo/releases/tag/v1",
            "https://huggingface.co/random-user/random-model",
            "https://openai.com.evil.example/new-model",
            "http://www.anthropic.com/news/test",
            "https://127.0.0.1/private", "file:///etc/passwd",
            "https://openai.com:8000/index/news",
            "https://user:secret@openai.com/index/news",
        ):
            with self.subTest(link=link):
                self.assertFalse(src.is_official_article(link))

    def test_ai_relevance_boundary(self):
        self.assertTrue(src.relevant_headline("A new AI image generation model"))
        self.assertTrue(src.relevant_headline("New voice agent API"))
        self.assertFalse(src.relevant_headline("How to repair a kitchen chair"))
        self.assertFalse(src.relevant_headline("Paid advertising system"))

    def test_hn_is_discovery_only_and_rejects_old_unofficial(self):
        calls = []
        def mock_api(url):
            calls.append(url)
            return {"hits": [
                {"url": "https://ai.meta.com/blog/llama-new-release/",
                 "title": "Meta releases new Llama AI model",
                 "created_at_i": int(NOW.timestamp()) - 100},
                {"url": "https://rumours.example.com/meta-llama",
                 "title": "Huge AI breakthrough",
                 "created_at_i": int(NOW.timestamp()) - 100},
                {"url": "https://openai.com/index/old-release",
                 "title": "Old AI model",
                 "created_at_i": int(NOW.timestamp()) - 10 * 86400},
                {"url": "https://github.com/random-user/test/releases/tag/ai",
                 "title": "New AI model",
                 "created_at_i": int(NOW.timestamp()) - 100},
            ]}
        found = src.discover_hn(NOW, request_json=mock_api)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["url"], "https://ai.meta.com/blog/llama-new-release/")
        self.assertEqual(len(calls), len(src.SEARCH_QUERIES))

    def test_hn_does_not_forge_official_publication_date(self):
        candidate = {
            "id": "id", "headline": "New AI model announced", "publisher": "ai.meta.com",
            "url": "https://ai.meta.com/blog/test",
            "published": NOW.isoformat(), "date_kind": "discovered_at",
            "source_text": "Only official facts. " * 45,
        }
        payload = ed.gemini_payload([candidate])
        message = payload["contents"][0]["parts"][0]["text"]
        self.assertIn('"source_published_utc": null', message)
        self.assertIn('"first_discovered_utc":', message)


if __name__ == "__main__":
    unittest.main()
