"""Offline regressions for the explicit, editor-approved site publisher."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "publish_approved_article", ROOT / "scripts" / "publish_approved_article.py"
)
PUBLISHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISHER)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "content" / "approved").mkdir(parents=True)
        (self.root / "assets").mkdir()
        (self.root / "assets" / "sample.svg").write_text("<svg/>", encoding="utf-8")
        shutil.copyfile(ROOT / "news.json", self.root / "news.json")
        shutil.copyfile(ROOT / "feed.xml", self.root / "feed.xml")
        self.article = {
            "slug": "sample-verified-news",
            "status": "approved",
            "approved_by": "editor",
            "approved_at": "2026-11-03",
            "title": "Пример <настоящей> новости",
            "summary": "Краткое изложение без непроверенных утверждений.",
            "published": "2026-11-03",
            "published_at_utc": "2026-11-03T15:00:00Z",
            "event_date": "2026-11-02",
            "section": "РАЗБОР",
            "source_url": "https://example.org/source",
            "source_title": "Первоисточник",
            "cover": "assets/sample.svg",
            "paragraphs": [
                {"type": "lead", "text": 'Заголовок <script>alert(1)</script> не исполнится.'},
                {"type": "p", "text": 'Текст & проверенный факт.'},
                {"type": "h2", "text": "Как это устроено"},
            ],
        }
        self.write_article()

    def write_article(self):
        p = self.root / "content" / "approved" / "sample-verified-news.json"
        p.write_text(json.dumps(self.article, ensure_ascii=False), encoding="utf-8")

    def test_preflight_never_writes_anything(self):
        prev = {p: p.read_bytes() for p in (self.root / "news.json", self.root / "feed.xml")}
        outputs = PUBLISHER.publish(self.root, "sample-verified-news", apply=False)
        self.assertEqual(len(outputs), 5)
        self.assertFalse((self.root / "articles").exists())
        self.assertFalse((self.root / "sitemap.xml").exists())
        for p, before in prev.items():
            self.assertEqual(p.read_bytes(), before)

    def test_approved_article_produces_html_rss_sitemap_and_catalog(self):
        PUBLISHER.publish(self.root, "sample-verified-news", apply=True)
        target = self.root / "articles" / "sample-verified-news" / "index.html"
        page = target.read_text(encoding="utf-8")
        self.assertIn('rel="canonical" href="https://iipike.ru/articles/sample-verified-news/"', page)
        self.assertIn('property="og:type" content="article"', page)
        self.assertIn("Пример &lt;настоящей&gt; новости", page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        records = json.loads((self.root / "news.json").read_text(encoding="utf-8"))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[-1]["id"], "sample-verified-news")
        catalog = (self.root / "articles" / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="sample-verified-news/"', catalog)
        self.assertIn('href="google-search-ai-links/"', catalog)
        rss = ET.fromstring((self.root / "feed.xml").read_text(encoding="utf-8"))
        self.assertEqual(len(rss.findall("./channel/item")), 2)
        guid = [x.findtext("guid") for x in rss.findall("./channel/item")
                if x.findtext("link", "").endswith("/google-search-ai-links/")][0]
        self.assertEqual(guid, "https://afterdark1000.github.io/iipike-site/articles/google-search-ai-links/")
        site = ET.fromstring((self.root / "sitemap.xml").read_text(encoding="utf-8"))
        locs = [x.text for x in site.iter() if x.tag.endswith("}loc")]
        self.assertEqual(len(locs), 4)
        self.assertIn("https://iipike.ru/articles/sample-verified-news/", locs)
        self.assertNotIn("drafts/", str(locs))
        with self.assertRaisesRegex(ValueError, "Already published"):
            PUBLISHER.publish(self.root, "sample-verified-news", apply=True)

    def test_rejects_unapproved_status(self):
        self.article["status"] = "draft"
        self.write_article()
        with self.assertRaisesRegex(ValueError, "approved"):
            PUBLISHER.publish(self.root, "sample-verified-news")

    def test_rejects_empty_editor_identity(self):
        self.article["approved_by"] = "  "
        self.write_article()
        with self.assertRaisesRegex(ValueError, "approved_by"):
            PUBLISHER.publish(self.root, "sample-verified-news")

    def test_rejects_unsafe_source_or_cover(self):
        self.article["source_url"] = "javascript:alert(1)"
        self.write_article()
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            PUBLISHER.publish(self.root, "sample-verified-news")
        self.article["source_url"] = "https://example.org/source"
        self.article["cover"] = "../drafts/image.png"
        self.write_article()
        with self.assertRaisesRegex(ValueError, "cover"):
            PUBLISHER.publish(self.root, "sample-verified-news")

    def test_rejects_slug_traversal_and_bad_body(self):
        with self.assertRaisesRegex(ValueError, "slug"):
            PUBLISHER.publish(self.root, "../../drafts/xyz")
        self.article["paragraphs"] = [{"type": "lead", "text": "Only one paragraph"}]
        self.write_article()
        with self.assertRaisesRegex(ValueError, "at least"):
            PUBLISHER.publish(self.root, "sample-verified-news")

    def test_malformed_first_paragraph_is_rejected_cleanly(self):
        self.article["paragraphs"] = ["not a block", {"type": "p", "text": "A paragraph"}]
        self.write_article()
        with self.assertRaisesRegex(ValueError, "lead"):
            PUBLISHER.publish(self.root, "sample-verified-news")

    def test_public_repo_catalog_links_are_static(self):
        content = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="articles/"', content)
        catalog = (ROOT / "articles" / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="google-search-ai-links/"', catalog)
        self.assertIn('rel="canonical" href="https://iipike.ru/articles/"', catalog)
        self.assertNotIn("НЕ ОПУБЛИКОВАНО", catalog)


if __name__ == "__main__":
    unittest.main()
