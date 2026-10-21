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
import publish_draft_preview as preview

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

    def preview_package(self, root, url):
        output = root / "editorial"
        output.mkdir()
        (output / "cover.png").write_bytes(b"offline cover fixture")
        (output / "draft.md").write_text(
            "# Проверка источника черновика\n\n"
            "*Черновик, НЕ ПУБЛИКОВАТЬ без проверки.*\n\n"
            "Тестовый текст для локального превью.\n\n"
            "**Первоисточник:** " + url, encoding="utf-8")
        (output / "report.json").write_text(json.dumps({
            "status": "awaiting_human_quality_review", "date": "2026-10-19",
            "source_url": url, "source_name": "Offline fixture",
            "source_date": "2026-10-19T08:00:00+00:00",
        }), encoding="utf-8")
        return output

    def test_preview_accepts_scanned_aws_and_nvidia_sources(self):
        for url in (
            "https://aws.amazon.com/blogs/machine-learning/structured-outputs-for-anthropic-claude-models-on-amazon-bedrock/",
            "https://aws.amazon.com/blogs/machine-learning/developers-can-now-access-sagemaker-studio-through-the-new-aws-experience/",
            "https://blogs.nvidia.com/blog/germany-wants-to-lead-the-world-in-industrial-ai-how-nvidia-will-help/",
        ):
            with self.subTest(url=url), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                rss = (f"<rss><channel><item><title>New AI release</title><link>{url}</link>"
                       "<pubDate>Mon, 19 Oct 2026 08:00:00 GMT</pubDate>"
                       "</item></channel></rss>").encode()
                selected, = ed.parse_feed(rss, "Offline fixture", NOW)
                output = self.preview_package(root, selected["url"])
                shelf = root / "drafts"
                with patch.object(preview, "ROOT", root):
                    self.assertTrue(preview.build(output, shelf))
                    self.assertTrue(preview.build(output, shelf))
                rows = json.loads((shelf / "index.json").read_text(encoding="utf-8"))
                self.assertEqual([row["id"] for row in rows], [selected["id"]])
                self.assertEqual(rows[0]["source_url"], url)
                page = (shelf / selected["id"] / "index.html").read_text(encoding="utf-8")
                self.assertIn('href="' + url + '"', page)
                self.assertIn("noindex, nofollow", page)
                self.assertIn("Автоматический черновик", page)
                self.assertEqual((shelf / selected["id"] / "cover.png").read_bytes(),
                                 b"offline cover fixture")

    def test_preview_rejects_unapproved_sources_before_writing(self):
        for url in (
            "http://aws.amazon.com/blogs/machine-learning/test/",
            "https://aws.amazon.com.evil.example/blogs/test/",
            "https://user:secret@aws.amazon.com/blogs/test/",
            "https://aws.amazon.com:8000/blogs/test/",
            "https://github.com/random-user/project/releases/tag/v1",
        ):
            with self.subTest(url=url), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                output = self.preview_package(root, url)
                shelf = root / "drafts"
                with patch.object(preview, "ROOT", root):
                    with self.assertRaisesRegex(ValueError, "Source must be"):
                        preview.build(output, shelf)
                self.assertFalse(shelf.exists())

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

    def test_editorial_archive_blocks_previous_official_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "news.json").write_text("[]", encoding="utf-8")
            data = (f"<rss><channel><item><title>Same announcement repackaged</title>"
                    f"<link>{GOOD_URL}</link>"
                    "<pubDate>Mon, 19 Oct 2026 08:00:00 GMT</pubDate>"
                    "</item></channel></rss>").encode("utf-8")
            def fetch(_):
                return data
            archive = [{"title": "В Дзене уже рассказывали про новый запуск",
                        "source_url": GOOD_URL, "status": "published",
                        "excerpt": ""}]
            with patch.object(ed, "ROOT", root):
                found = ed.select_candidates(NOW, {"drafted": []}, fetcher=fetch,
                                             discovery=lambda *a, **kw: [],
                                             read_article=lambda _: "Source article " * 90,
                                             archive_entries=archive)
            self.assertEqual(found, [])

    def test_archive_headlines_are_provided_for_semantic_comparison(self):
        data = ed.gemini_payload([{
            "id": "test", "publisher": "Google", "headline": "New AI model",
            "url": GOOD_URL, "published": NOW.isoformat(),
            "source_text": "Official source details " * 35
        }], [{"title": "ИИ-модель уже вышла", "status": "published",
              "excerpt": "Обзор запуска"}])
        prompt = data["contents"][0]["parts"][0]["text"]
        self.assertIn("ИИ-модель уже вышла", prompt)
        self.assertIn("сверь КАЖДОГО кандидата".casefold()[:10], prompt.casefold())

    def test_daily_draft_idempotency_skips_all_external_calls(self):
        """More backup cron triggers must not spend tokens after today's success."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stamp = dt.datetime.now(ed.NOW)
            state_file = root / "editorial_state.json"
            status_file = root / "editorial_status.json"
            state = {"schema_version": 1, "drafted": [{
                "id": "already-created", "utc_date": stamp.date().isoformat(),
                "source_url": GOOD_URL, "source_title": "Already done"
            }]}
            state_file.write_text(json.dumps(state), encoding="utf-8")
            with (patch.object(ed, "ROOT", root),
                  patch.object(ed, "STATE", state_file),
                  patch.object(ed, "STATUS", status_file),
                  patch.object(ed, "read_editorial_archive",
                               side_effect=AssertionError("Already made today's draft")),
                  patch.object(ed, "ask_gemini",
                               side_effect=AssertionError("Do not call Gemini twice")),
                  patch.object(ed, "flux_generate",
                               side_effect=AssertionError("Do not call FLUX twice"))):
                ed.main()
            self.assertEqual(json.loads(state_file.read_text()), state)
            self.assertEqual(json.loads(status_file.read_text())["status"], "already")

    def test_editorial_cron_has_staggered_retries(self):
        """GitHub may drop schedule events; maintain multiple daily chances."""
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/editorial-draft.yml").read_text(encoding="utf-8")
        import re
        crons = re.findall(r'^\s+- cron: "(\d{1,2}) (\d{1,2}) \* \* \*"', workflow,
                           flags=re.MULTILINE)
        self.assertGreaterEqual(len(crons), 6)
        self.assertEqual(len(crons), len(set(crons)))
        self.assertTrue(all(0 < int(minute) < 60 for minute, _ in crons))

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
