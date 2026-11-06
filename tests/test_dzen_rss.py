"""Offline tests for Dzen full-text RSS (NO Dzen publishing)."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET

from scripts.build_dzen_rss import CONTENT_NS, cdata, read_settings, render

UTC = dt.timezone.utc
DZEN_LINK = "https://dzen.ru/a/auxfoJL-EAlB7Skz"
SITE_LINK = "https://iipike.ru/articles/openai-linux-root-948-20261104/"
SOURCE = (
    "**OpenAI** изучила Firefox и нашла опасные ошибки. " * 7
    + "\n\n## Проверка безопасности\n\n"
    + "Прежние испытания [описаны в Дзене](" + DZEN_LINK + "). "
    + "Это проверенная редакционная ссылка на прежний выпуск. " * 4
    + "\n\n**Первоисточник:** [OpenAI](https://openai.com/index/introducing-gpt-6-cyber/)"
)
SLUG = "gpt-6-cyber-firefox-81-vulnerabilities-20261105"
PUB = "2026-11-06T12:45:36Z"


class DzenRssTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for path in ("content/approved", "articles/" + SLUG, "assets/editorial", "data"):
            (self.root / path).mkdir(parents=True, exist_ok=True)
        self.cover = self.root / "assets/editorial" / (SLUG + ".webp")
        self.cover.write_bytes(b"WEBP TEST" * 120)
        self.row = {
            "id": SLUG, "url": "articles/" + SLUG + "/",
            "title": "GPT-6 Cyber нашёл 81 уязвимость Firefox",
            "summary": "Mozilla получила результаты тестирования.",
            "published_at_utc": PUB,
            "cover": "assets/editorial/" + SLUG + ".webp",
        }
        from scripts.site_rich_text import markdown_to_blocks
        self.source = {
            "slug": SLUG, "status": "approved",
            "approved_by": "Редактор ХПИИ",
            "title": self.row["title"],
            "published_at_utc": PUB,
            "cover": self.row["cover"],
            "article_markdown": SOURCE,
            "paragraphs": markdown_to_blocks(SOURCE),
            "site_crosslinks": {"6aec5fa092fe100941ed2933": "openai-linux-root-948-20261104"},
        }
        self.approved_path = self.root / "content/approved" / (SLUG + ".json")
        self.approved_path.write_text(json.dumps(self.source, ensure_ascii=False), encoding="utf-8")
        self.page = self.root / "articles" / SLUG / "index.html"
        self.page.write_text("<html>Published</html>", encoding="utf-8")
        self.config_path = self.root / "data/dzen_rss_export.json"
        self.settings = {"schema_version": 1, "mode": "standby",
                         "cutover_at_utc": None, "max_items": 40}
        self.save_config()

    def save_config(self):
        self.config_path.write_text(json.dumps(self.settings), encoding="utf-8")

    def items(self, xml):
        root = ET.fromstring(xml)
        return root.findall("./channel/item")

    def test_full_original_dzen_body_cover_guid_and_date(self):
        original = self.approved_path.read_bytes()
        output = render(self.root, [self.row])
        items = self.items(output)
        self.assertEqual(len(items), 1)
        item = items[0]
        url = "https://iipike.ru/articles/" + SLUG + "/"
        self.assertEqual(item.findtext("title"), self.row["title"])
        self.assertEqual(item.findtext("link"), url)
        self.assertEqual(item.findtext("guid"), url)
        self.assertEqual(item.findtext("pubDate"), "Fri, 06 Nov 2026 12:45:36 GMT")
        body = item.findtext("{" + CONTENT_NS + "}encoded")
        self.assertIn("<strong>OpenAI</strong>", body)
        self.assertIn("<h2>Проверка безопасности</h2>", body)
        self.assertIn('href="' + DZEN_LINK + '"', body)
        self.assertNotIn('href="' + SITE_LINK + '"', body)
        self.assertIn('src="https://iipike.ru/' + self.row["cover"] + '"', body)
        enclosure = item.find("enclosure")
        self.assertEqual(enclosure.get("url"), "https://iipike.ru/" + self.row["cover"])
        self.assertEqual(enclosure.get("length"), str(self.cover.stat().st_size))
        self.assertEqual(enclosure.get("type"), "image/webp")
        self.assertEqual(self.approved_path.read_bytes(), original)
        self.assertEqual(render(self.root, [self.row]), output)

    def test_only_published_and_approved_site_first_stories(self):
        self.page.unlink()
        self.assertEqual(len(self.items(render(self.root, [self.row]))), 0)
        self.page.write_text("Published", encoding="utf-8")
        altered = [{**self.row, "dzen_id": "6aec5fa092fe100941ed2933"}]
        self.assertEqual(len(self.items(render(self.root, altered))), 0)
        mirrored = [{**self.row, "site_first_dzen_id": "6aec5fa092fe100941ed2933"}]
        self.assertEqual(len(self.items(render(self.root, mirrored))), 0)
        self.source["status"] = "draft"
        self.approved_path.write_text(json.dumps(self.source), encoding="utf-8")
        self.assertEqual(len(self.items(render(self.root, [self.row]))), 0)

    def test_newly_staged_approved_article_is_exported_in_same_commit(self):
        self.page.unlink()
        self.approved_path.unlink()
        self.assertEqual(len(self.items(render(self.root, [self.row]))), 0)
        self.assertEqual(len(self.items(render(self.root, [self.row], staged=self.source))), 1)

    def test_cutover_excludes_old_manual_dzen_materials(self):
        self.settings["mode"] = "active"
        self.settings["cutover_at_utc"] = "2026-11-07T00:00:00Z"
        self.save_config()
        self.assertEqual(len(self.items(render(self.root, [self.row]))), 0)
        self.settings["cutover_at_utc"] = "2026-11-06T12:45:36Z"
        self.save_config()
        self.assertEqual(len(self.items(render(self.root, [self.row]))), 1)
        self.assertEqual(len(self.items(render(self.root, [self.row]))), 1)

    def test_cutover_cannot_be_active_without_timestamp(self):
        self.settings["mode"] = "active"
        self.save_config()
        with self.assertRaisesRegex(ValueError, "timestamp"):
            read_settings(self.root)
        self.settings["mode"] = "untrusted"
        self.save_config()
        with self.assertRaisesRegex(ValueError, "mode"):
            read_settings(self.root)

    def test_duplicate_site_id_not_exported_twice(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            render(self.root, [self.row, self.row])

    def test_xml_cdata_and_editorial_html_are_safe(self):
        self.assertEqual(cdata("hello]]>world"), "<![CDATA[hello]]]]><![CDATA[>world]]>")
        self.source["article_markdown"] = SOURCE.replace(
            "проверенная редакционная", "<script>запуск</script> редакционная"
        )
        from scripts.site_rich_text import markdown_to_blocks
        self.source["paragraphs"] = markdown_to_blocks(self.source["article_markdown"])
        self.approved_path.write_text(json.dumps(self.source), encoding="utf-8")
        text = self.items(render(self.root, [self.row]))[0].findtext("{" + CONTENT_NS + "}encoded")
        self.assertIn("&lt;script&gt;", text)
        self.assertNotIn("<script>", text)
        self.assertIn('href="' + DZEN_LINK + '"', text)

    def test_missing_or_corrupted_source_is_never_exported(self):
        self.source["paragraphs"][0]["text"] = "ИЗМЕНЁННЫЙ ТЕКСТ"
        self.approved_path.write_text(json.dumps(self.source), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "differs"):
            render(self.root, [self.row])


if __name__ == "__main__":
    unittest.main()
