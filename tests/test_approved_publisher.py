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
            "rubric": "news",
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
        self.assertEqual(len(outputs), 9)
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
        self.assertEqual(len(records), len(json.loads((ROOT / "news.json").read_text(encoding="utf-8"))) + 1)
        self.assertEqual(records[-1]["id"], "sample-verified-news")
        catalog = (self.root / "articles" / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="sample-verified-news/"', catalog)
        self.assertIn('href="google-search-ai-links/"', catalog)
        rss = ET.fromstring((self.root / "feed.xml").read_text(encoding="utf-8"))
        self.assertEqual(len(rss.findall("./channel/item")), len(records))
        guid = [x.findtext("guid") for x in rss.findall("./channel/item")
                if x.findtext("link", "").endswith("/google-search-ai-links/")][0]
        self.assertEqual(guid, "https://afterdark1000.github.io/iipike-site/articles/google-search-ai-links/")
        site = ET.fromstring((self.root / "sitemap.xml").read_text(encoding="utf-8"))
        locs = [x.text for x in site.iter() if x.tag.endswith("}loc")]
        self.assertEqual(len(locs), len(records) + 2 + 4)
        self.assertIn("https://iipike.ru/rubrics/news/", locs)
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

    def test_modified_date_is_machine_only_and_sitemap_lastmod(self):
        self.article["modified_at_utc"] = "2026-11-03T16:00:00Z"
        self.write_article()
        outputs = PUBLISHER.publish(self.root, "sample-verified-news", apply=True)
        html = outputs[self.root / "articles" / "sample-verified-news" / "index.html"]
        self.assertIn('article:published_time" content="2026-11-03T15:00:00Z"', html)
        self.assertIn('article:modified_time" content="2026-11-03T16:00:00Z"', html)
        self.assertIn('"datePublished": "2026-11-03T15:00:00Z"', html)
        self.assertIn('"dateModified": "2026-11-03T16:00:00Z"', html)
        self.assertIn("Опубликовано: 3 ноября 2026", html)
        self.assertNotIn("Обновлено:", html)
        self.assertNotIn("На сайте:", html)
        sitemap = ET.fromstring(outputs[self.root / "sitemap.xml"])
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        entries = sitemap.findall(".//s:url", ns)
        migrated = next(row for row in entries if "sample-verified-news" in row.findtext("s:loc", "", ns))
        self.assertEqual(migrated.findtext("s:lastmod", "", ns), "2026-11-03T16:00:00Z")
        self.assertEqual(sum(row.find("s:lastmod", ns) is not None for row in entries), 1)
        manifest = json.loads(outputs[self.root / "news.json"])
        self.assertEqual(manifest[-1]["published"], "2026-11-03")
        self.assertEqual(manifest[-1]["modified_at_utc"], "2026-11-03T16:00:00Z")

    def test_rejects_invalid_or_future_modification_time(self):
        for changed in ("2026-11-03T14:00:00Z", "2099-01-01T00:00:00Z", "invalid"):
            self.article["modified_at_utc"] = changed
            self.write_article()
            with self.assertRaisesRegex(ValueError, "modified_at_utc"):
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
