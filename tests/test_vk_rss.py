"""Offline tests: VK RSS must be safe, image-first and opt-in."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from PIL import Image
from scripts import build_vk_rss as vk


class VKRSS(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "assets/editorial").mkdir(parents=True)
        (self.root / "data").mkdir()
        self.cutover = "2026-11-14T00:00:00Z"

    def row(self, slug, date="2026-11-14T07:00:00Z", **changes):
        (self.root / "articles" / slug).mkdir(parents=True, exist_ok=True)
        (self.root / "articles" / slug / "index.html").write_text("<h1>Published</h1>")
        path = self.root / "assets/editorial" / (slug + ".webp")
        Image.new("RGB", (1600, 900), (80, 120, 180)).save(path, "WEBP")
        return {"id": slug, "url": f"articles/{slug}/", "published_at_utc": date,
                "title": "Новость <А> & друзья", "summary": "Сайт говорит: 1 < 2 & всё хорошо.",
                "cover": f"assets/editorial/{slug}.webp", **changes}

    def active(self):
        return {"schema_version": 1, "mode": "active",
                "cutover_at_utc": self.cutover, "max_items": 12}

    def test_standby_never_exports_old_or_new_items(self):
        xml, assets = vk.render(
            self.root, [self.row("existing-story")],
            settings={"schema_version": 1, "mode": "standby",
                      "cutover_at_utc": None, "max_items": 12})
        self.assertFalse(assets)
        self.assertEqual(len(ET.fromstring(xml).findall("./channel/item")), 0)
        self.assertFalse((self.root / "assets/vk").exists())

    def test_vk_editorial_copy_only_changes_feed_text(self):
        row = self.row("editorial-vk-story")
        row["vk_title"] = "🧬 ИИ нашёл СЛЕД В ДНК"
        row["vk_summary"] = "Учёные проверяют, как изменения ДНК влияют на гены."
        xml, images = vk.render(self.root, [row], settings=self.active())
        item = ET.fromstring(xml).find("./channel/item")
        self.assertEqual(item.findtext("title"), row["vk_title"])
        desc = item.findtext("description")
        self.assertIn(row["vk_summary"], desc)
        self.assertNotIn(row["summary"], desc)
        self.assertIn("alt=\\\"", desc)
        self.assertEqual(item.findtext("link"),
                         "https://iipike.ru/articles/editorial-vk-story/")
        self.assertEqual(item.findtext("guid"),
                         "https://iipike.ru/articles/editorial-vk-story/")
        self.assertEqual(len(images), 1)

    def test_missing_vk_copy_keeps_original_title_summary(self):
        row = self.row("plain-story")
        xml, _ = vk.render(self.root, [row], settings=self.active())
        item = ET.fromstring(xml).find("./channel/item")
        self.assertEqual(item.findtext("title"), row["title"])
        self.assertIn("Сайт говорит:", item.findtext("description"))

    def test_new_article_has_jpeg_and_first_image_in_description(self):
        rows = [self.row("past-story", date="2026-11-13T18:00:00Z"),
                self.row("new-story")]
        xml, assets = vk.render(self.root, rows, settings=self.active())
        self.assertEqual(len(assets), 1)
        target, jpg = next(iter(assets.items()))
        self.assertEqual(target.name, "new-story.jpg")
        with Image.open(io.BytesIO(jpg)) as img:
            self.assertEqual(img.format, "JPEG")
            self.assertEqual(img.size, (1280, 720))
        items = ET.fromstring(xml).findall("./channel/item")
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertTrue(item.findtext("description").startswith(
            '<p><img src="https://iipike.ru/assets/vk/new-story.jpg"'))
        self.assertIn("&lt;А&gt;", item.findtext("description"))
        self.assertEqual(item.find("enclosure").get("type"), "image/jpeg")
        self.assertEqual(item.findtext("pubDate"), "Sat, 14 Nov 2026 07:00:00 GMT")
        self.assertEqual(item.findtext("link"),
                         "https://iipike.ru/articles/new-story/")

    def test_dzen_and_drafts_are_excluded(self):
        rows = [self.row("dzen-copy", dzen_id="123"), self.row("unpublished-story")]
        (self.root / "articles/unpublished-story/index.html").unlink()
        xml, assets = vk.render(self.root, rows, settings=self.active())
        self.assertFalse(assets)
        self.assertFalse(ET.fromstring(xml).findall("./channel/item"))

    def test_export_and_readonly_check(self):
        row = self.row("released-story")
        (self.root / "news.json").write_text(json.dumps([row], ensure_ascii=False))
        (self.root / vk.CONFIG).write_text(json.dumps(self.active()))
        self.assertEqual(vk.export(self.root), 1)
        self.assertEqual(vk.export(self.root, check=True), 1)
        (self.root / "assets/vk/released-story.jpg").unlink()
        with self.assertRaisesRegex(ValueError, "missing/stale"):
            vk.export(self.root, check=True)

    def test_pilot_freezes_on_first_new_article(self):
        rows = [
            self.row("older-story", date="2026-11-13T18:30:00Z"),
            self.row("pilot-story", date="2026-11-14T07:00:00Z"),
            self.row("later-story", date="2026-11-14T08:00:00Z"),
        ]
        pilot = {"schema_version": 1, "mode": "pilot",
                 "cutover_at_utc": self.cutover, "max_items": 1}
        xml, assets = vk.render(self.root, rows, settings=pilot)
        items = ET.fromstring(xml).findall("./channel/item")
        self.assertEqual(len(items), 1)
        self.assertIn("pilot-story", items[0].findtext("link"))
        self.assertEqual([p.name for p in assets], ["pilot-story.jpg"])
        (self.root / vk.CONFIG).write_text(json.dumps(pilot))
        self.assertEqual(vk.settings_from(self.root), pilot)
        pilot["max_items"] = 2
        (self.root / vk.CONFIG).write_text(json.dumps(pilot))
        with self.assertRaisesRegex(ValueError, "exactly one"):
            vk.settings_from(self.root)

    def test_cover_must_match_story(self):
        row = self.row("safe-story")
        row["cover"] = "assets/editorial/other-story.webp"
        xml, assets = vk.render(self.root, [row], settings=self.active())
        self.assertFalse(assets)
        self.assertFalse(ET.fromstring(xml).findall("./channel/item"))

    def test_standby_with_cutover_fails_closed(self):
        (self.root / vk.CONFIG).write_text(json.dumps({
            "schema_version": 1, "mode": "standby",
            "cutover_at_utc": "2026-11-14T00:00:00Z", "max_items": 12}))
        with self.assertRaisesRegex(ValueError, "Standby"):
            vk.settings_from(self.root)


if __name__ == "__main__":
    unittest.main()
