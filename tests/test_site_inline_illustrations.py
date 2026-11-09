"""Regression: real in-article images are safe, exact, and release-blocking."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from scripts.site_rich_text import markdown_to_blocks, render_blocks
from scripts.site_first_inbox import stage, validate_story
from scripts.publish_approved_article import approved_article, render_article


ID = "sample-inline-illustration-20261109"
NAME = "family-checklist.webp"
SOURCE = f"illustrations/{ID}/{NAME}"
STAMP = dt.datetime(2026, 11, 9, 11, 0, tzinfo=dt.timezone.utc)
LEAD = "Редактор сохранил проверенную статью с полезной памяткой для всей семьи. " * 9
BODY = (LEAD + "\n\n## Практические действия\n\n"
        "![Памятка о безопасной проверке голосового звонка](" + SOURCE + ")\n\n"
        "Проверьте сообщение по ранее известному номеру и позвоните близким.")


class InlineIllustrationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "news.json").write_text("[]\n", encoding="utf-8")
        self.inbox = self.root / "editorial_inbox" / "stories" / f"{ID}.json"
        self.inbox.parent.mkdir(parents=True)
        self.cover = self.root / "editorial_inbox" / "covers" / f"{ID}.webp"
        self.cover.parent.mkdir(parents=True)
        self.image = self.root / "editorial_inbox" / SOURCE
        self.image.parent.mkdir(parents=True)
        self.data = {
            "schema_version": 1, "id": ID, "status": "editor_approved",
            "approved_by": "human_editor", "approved_at": "2026-11-09",
            "title": "Памятка с иллюстрацией для сайта",
            "dzen_title": "Памятка с иллюстрацией для сайта",
            "summary": "Проверенный обзор с простой памяткой и точными ссылками.",
            "rubric": "skynet", "section": "СКАЙНЕТ РЯДОМ",
            "source_url": "https://example.org/approved-safety-guide",
            "source_title": "Официальная рекомендация", "related_dzen_ids": [],
            "article_markdown": BODY,
        }
        self.save_story()

    def save_story(self):
        self.inbox.write_text(json.dumps(self.data, ensure_ascii=False) + "\n",
                              encoding="utf-8")

    @staticmethod
    def save_image(path, size):
        Image.effect_noise(size, 38).convert("RGB").save(path, "WEBP", quality=82)

    def test_image_is_an_ordered_accessible_figure(self):
        blocks = markdown_to_blocks(BODY)
        self.assertEqual([x["type"] for x in blocks], ["lead", "h2", "image", "p"])
        html = render_blocks(blocks)
        self.assertIn('class="editorial-inline-figure"', html)
        self.assertIn('alt="Памятка о безопасной проверке голосового звонка"', html)
        self.assertIn(f'src="../../assets/editorial/inline/{ID}/{NAME}"', html)
        self.assertLess(html.index("<h2>"), html.index('<figure class='))
        self.assertLess(html.index('<figure class='), html.index("Проверьте сообщение"))

    def test_missing_image_blocks_release_even_with_real_cover(self):
        self.save_image(self.cover, (960, 540))
        self.assertIsNone(stage(self.root, ID, now=STAMP, apply=True))
        self.assertFalse((self.root / "content" / "approved").exists())

    def test_valid_image_is_copied_and_provenance_preserved(self):
        self.save_image(self.cover, (960, 540))
        self.save_image(self.image, (700, 810))
        result = stage(self.root, ID, now=STAMP, apply=True)
        expected = self.root / "assets" / "editorial" / "inline" / ID / NAME
        self.assertTrue(expected.is_file())
        self.assertEqual(expected.read_bytes(), self.image.read_bytes())
        self.assertEqual(result["article_markdown"], BODY)
        self.assertEqual(approved_article(self.root, ID)["article_markdown"], BODY)
        html = render_article(result)
        self.assertIn(f'assets/editorial/inline/{ID}/{NAME}', html)
        self.assertIn('Памятка о безопасной проверке', html)
        expected.unlink()
        with self.assertRaisesRegex(ValueError, "Missing approved local illustration"):
            approved_article(self.root, ID)

    def test_cross_story_and_path_traversal_are_rejected(self):
        for src in (
            f"illustrations/another-story/{NAME}",
            f"illustrations/{ID}/../{NAME}",
            "https://evil.example/file.webp",
            f"illustrations/{ID}/bad.svg",
            f"illustrations/{ID}/foo.webp?x=1",
            f"illustrations/{ID}/two words.webp",
        ):
            with self.subTest(src=src):
                test = BODY.replace(SOURCE, src)
                if src.startswith("illustrations/another-story/"):
                    self.data["article_markdown"] = test
                    self.save_story()
                    with self.assertRaisesRegex(ValueError, "same approved story ID"):
                        validate_story(self.root, ID, today=dt.date(2026, 11, 9))
                else:
                    with self.assertRaises(ValueError):
                        markdown_to_blocks(test)

    def test_non_image_bytes_fail_closed(self):
        self.save_image(self.cover, (960, 540))
        self.image.write_bytes(b"not a real picture" * 500)
        with self.assertRaisesRegex(ValueError, "cannot be decoded"):
            stage(self.root, ID, now=STAMP)


if __name__ == "__main__":
    unittest.main()
