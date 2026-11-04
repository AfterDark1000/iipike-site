"""Regression: ChatGPT editor + cover from any chat, site-first safety."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from scripts.site_first_inbox import stage, validate_story, cover_info
from scripts.publish_approved_article import approved_article

ID = "sample-chatgpt-editor-story-20261104"
UTC = dt.datetime(2026, 11, 4, 11, 15, 32, tzinfo=dt.timezone.utc)


class SiteFirstInboxTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.story_path = self.root / "editorial_inbox" / "stories" / (ID + ".json")
        self.cover_path = self.root / "editorial_inbox" / "covers" / (ID + ".webp")
        self.story_path.parent.mkdir(parents=True)
        self.cover_path.parent.mkdir(parents=True)
        self.story = {
            "schema_version": 1, "id": ID, "status": "editor_approved",
            "approved_by": "human_editor", "approved_at": "2026-11-04",
            "title": "Проверенная новость об ИИ — редакционный пример",
            "dzen_title": "Проверенная новость об ИИ — редакционный пример",
            "summary": "Проверенный материал со ссылкой на первоисточник и корректной датой.",
            "rubric": "news", "section": "НОВОСТИ ИИ",
            "source_url": "https://example.org/story/verified",
            "source_title": "Проверенный первоисточник",
            "threads_queue_id": ID, "x_queue_id": ID,
            "related_dzen_ids": [],
            "paragraphs": [
                {"type": "lead", "text": "Речь идёт о проверенной новости из первоисточника. " * 6},
                {"type": "p", "text": "Редактор подтверждает факты и сохраняет исходный заголовок. " * 6},
                {"type": "h2", "text": "Зачем это нужно"},
                {"type": "p", "text": "Только после обложки статья готовится к выпуску на сайт. " * 6},
            ],
        }
        (self.root / "news.json").write_text("[]\n", encoding="utf-8")
        self.save_story()

    def save_story(self):
        self.story_path.write_text(
            json.dumps(self.story, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def save_cover(self, *, size=(960, 540), path=None):
        dest = path or self.cover_path
        # A decodable nontrivial image, not a file renamed to .webp.
        im = Image.effect_noise(size, 56).convert("RGB")
        im.save(dest, format="WEBP", quality=88)
        self.assertGreater(dest.stat().st_size, 15_000)

    def test_no_cover_leaves_site_unchanged(self):
        self.assertIsNone(stage(self.root, ID, apply=True, now=UTC))
        self.assertFalse((self.root / "content").exists())
        self.assertFalse((self.root / "assets").exists())

    def test_real_cover_and_text_create_approved_site_source_only(self):
        self.save_cover()
        preview = stage(self.root, ID, apply=False, now=UTC)
        self.assertEqual(preview["published_at_utc"], "2026-11-04T11:15:32Z")
        self.assertEqual(preview["published"], "2026-11-04")
        self.assertFalse((self.root / "content").exists())
        stage(self.root, ID, apply=True, now=UTC)
        approved = approved_article(self.root, ID)
        self.assertEqual(approved["title"], self.story["dzen_title"])
        self.assertEqual(approved["published_at_utc"], "2026-11-04T11:15:32Z")
        self.assertTrue((self.root / approved["cover"]).exists())
        self.assertFalse((self.root / "articles").exists(), "Stage cannot publish a site page")
        self.assertNotIn("dzen_id", approved)
        self.assertNotIn("dzen_url", approved)
        with self.assertRaisesRegex(ValueError, "Already staged"):
            stage(self.root, ID, apply=True, now=UTC)

    def test_editor_rich_formatting_survives_inbox_to_site_html(self):
        self.story["paragraphs"] = [
            {"type": "lead", "text": "Первый абзац с **жирным** словом и *курсивом*. " * 5},
            {"type": "p", "text": "Подробности в [первоисточнике](https://example.org/story/verified). " * 4},
            {"type": "h2", "text": "Что произошло"},
            {"type": "ul", "items": ["**Первое:** результат исследования", "Второе: практика"]},
            {"type": "ol", "items": ["Редактор", "Художник", "Сайт", "Дзен"]},
            {"type": "quote", "text": "Подтверждённое *заявление* для читателей.",
             "attribution": "Автор исследования"},
        ]
        self.save_story()
        self.save_cover()
        staged = stage(self.root, ID, apply=True, now=UTC)
        from scripts.publish_approved_article import render_article
        html = render_article(staged)
        self.assertIn("<strong>жирным</strong>", html)
        self.assertIn("<em>курсивом</em>", html)
        self.assertIn('<ul class="editorial-list"><li><strong>Первое:</strong>', html)
        self.assertIn('<ol class="editorial-list"><li>Редактор</li>', html)
        self.assertIn('<blockquote class="editorial-quote">', html)
        self.assertIn('href="https://example.org/story/verified"', html)
        self.assertEqual(staged["paragraphs"], self.story["paragraphs"])

    def test_refuse_unapproved_or_tampered_editorial_article(self):
        self.save_cover()
        for field, new_value in (
            ("status", "draft"),
            ("approved_by", "llm"),
            ("dzen_title", "Другой заголовок"),
            ("source_url", "http://untrusted.example/test"),
            ("source_url", "https://user:pass@example.org/"),
            ("id", "other-story"),
        ):
            with self.subTest(field=field, value=new_value):
                original = self.story[field]
                self.story[field] = new_value
                self.save_story()
                with self.assertRaises(ValueError):
                    stage(self.root, ID, apply=True, now=UTC)
                self.story[field] = original
        self.story["published_at_utc"] = "2026-10-01T00:00:00Z"
        self.save_story()
        with self.assertRaisesRegex(ValueError, "forbidden"):
            stage(self.root, ID, apply=True, now=UTC)

    def test_stable_id_prevents_wrong_cover_association(self):
        self.save_cover(path=self.root / "editorial_inbox" / "covers" / "another-story.webp")
        self.assertIsNone(cover_info(self.root, ID))
        self.assertIsNone(stage(self.root, ID, now=UTC))
        self.save_cover()
        (self.root / "editorial_inbox" / "covers" / (ID + ".png")).write_bytes(b"fake")
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            stage(self.root, ID, apply=True, now=UTC)

    def test_reject_fake_image_wrong_aspect_or_incomplete_text(self):
        self.cover_path.write_bytes(b"RIFF" + b"?" * 30000)
        with self.assertRaisesRegex(ValueError, "decoded"):
            stage(self.root, ID, apply=True, now=UTC)
        self.save_cover(size=(900, 900))
        with self.assertRaisesRegex(ValueError, "16:9"):
            stage(self.root, ID, apply=True, now=UTC)
        self.save_cover()
        self.story["paragraphs"] = [{"type": "lead", "text": "Слишком коротко."}]
        self.save_story()
        with self.assertRaisesRegex(ValueError, "at least two"):
            stage(self.root, ID, apply=True, now=UTC)

    def test_no_duplicate_story_or_source(self):
        self.save_cover()
        (self.root / "news.json").write_text(
            json.dumps([{
                "id": "different-id", "url": "articles/different-id/",
                "title": "Другая статья", "source_url": self.story["source_url"],
            }]), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            stage(self.root, ID, apply=True, now=UTC)

    def test_no_future_approval(self):
        self.save_cover()
        self.story["approved_at"] = "2026-11-05"
        self.save_story()
        with self.assertRaisesRegex(ValueError, "future"):
            validate_story(self.root, ID, today=dt.date(2026, 11, 4))


if __name__ == "__main__":
    unittest.main()
