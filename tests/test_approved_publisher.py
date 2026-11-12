"""Offline regressions for the explicit, editor-approved site publisher."""
import importlib.util
import json
from pathlib import Path
from scripts.site_topics import TOPICS, active_topics
from scripts.site_entities import entity_urls, load_registry
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
        shutil.copyfile(ROOT / "index.html", self.root / "index.html")
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

    def test_explicit_company_product_metadata_updates_only_matching_archives(self):
        self.article["companies"] = ["disney", "adobe"]
        self.article["products"] = ["firefly"]
        self.write_article()
        original_registry = (ROOT / "data/entity_registry.json").read_bytes()
        outputs = PUBLISHER.publish(self.root, "sample-verified-news", apply=False)
        registry_path = self.root / "data/entity_registry.json"
        self.assertIn(registry_path, outputs)
        selected = json.loads(outputs[registry_path])
        companies = {x["key"]: x for x in selected["companies"]}
        products = {x["key"]: x for x in selected["products"]}
        for key in ("disney", "adobe"):
            self.assertIn("sample-verified-news", companies[key]["article_ids"])
            self.assertIn(self.root / "entities/companies" / key / "index.html", outputs)
        self.assertIn("sample-verified-news", products["firefly"]["article_ids"])
        self.assertIn(self.root / "entities/products/firefly/index.html", outputs)
        page = outputs[self.root / "articles/sample-verified-news/index.html"]
        for key in ("adobe", "disney"):
            self.assertIn("../../entities/companies/" + key + "/", page)
        self.assertIn("../../entities/products/firefly/", page)
        self.assertIn('class="article-entity-links"', page)
        self.assertFalse(registry_path.exists(), "Preflight must not write a registry")
        self.assertEqual((ROOT / "data/entity_registry.json").read_bytes(), original_registry)
        PUBLISHER.publish(self.root, "sample-verified-news", apply=True)
        self.assertEqual(registry_path.read_text(encoding="utf-8"), outputs[registry_path])
        article = json.loads((self.root / "news.json").read_text(encoding="utf-8"))[-1]
        self.assertEqual(article["companies"], ["disney", "adobe"])
        self.assertEqual(article["products"], ["firefly"])
        self.assertEqual((ROOT / "data/entity_registry.json").read_bytes(), original_registry)

    def test_regenerated_tagged_article_uses_historical_css_line_layout(self):
        # A release refreshes old approved pages. That re-render must not
        # introduce a same-line CSS link which fails the header-only regression.
        import json
        from scripts.site_entities import render_article_entity_nav
        ident = "disney-adobe-firefly-foundry-alliance-20261109"
        source = ROOT / "content" / "approved" / (ident + ".json")
        self.assertTrue(source.is_file())
        data = json.loads(source.read_text(encoding="utf-8"))
        html = PUBLISHER.render_article(data, json.loads(
            (ROOT / "news.json").read_text(encoding="utf-8")))
        base = '<link rel="stylesheet" href="../../assets/site.css">'
        css = '<link rel="stylesheet" href="../../assets/entities.css">'
        self.assertIn(base + "\n" + css, html)
        self.assertIn(render_article_entity_nav(ident, load_registry(ROOT)), html)
        self.assertEqual(html.count(css), 1)

    def test_product_selects_its_owner_without_naming_unrelated_companies(self):
        self.article["companies"], self.article["products"] = [], ["grok"]
        self.write_article()
        outputs = PUBLISHER.publish(self.root, "sample-verified-news")
        page = outputs[self.root / "articles/sample-verified-news/index.html"]
        self.assertIn("../../entities/companies/xai/", page)
        self.assertIn("../../entities/products/grok/", page)
        self.assertNotIn("../../entities/companies/google/", page)
        self.assertEqual(json.loads(outputs[self.root / "news.json"])[-1]["companies"], ["xai"])

    def test_unknown_editorial_company_product_never_publishes(self):
        self.article["companies"] = ["unknown-robotic-startup"]
        self.write_article()
        with self.assertRaisesRegex(ValueError, "Unknown"):
            PUBLISHER.publish(self.root, "sample-verified-news", apply=True)
        self.assertFalse((self.root / "data/entity_registry.json").exists())
        self.assertFalse((self.root / "articles").exists())

    def test_committed_archive_order_matches_homepage_newest_first(self):
        import re
        from scripts.site_home import sorted_published
        records = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
        page = (ROOT / "articles/index.html").read_text(encoding="utf-8")
        ids = re.findall(r'<a class="archive-card" href="([^"/]+)/">', page)
        self.assertEqual(ids, [r["id"] for r in sorted_published(records)])

    def test_archive_and_rss_sort_same_day_by_actual_publication_time(self):
        # Alphabetical ID order used to put a morning story above a later one.
        examples = [
            {"id": "z-early", "published": "2026-11-12",
             "published_at_utc": "2026-11-12T06:30:00Z",
             "title": "Morning edition"},
            {"id": "a-late", "published": "2026-11-12",
             "published_at_utc": "2026-11-12T07:50:30Z",
             "title": "Afternoon edition"},
            {"id": "m-older", "published": "2026-11-11",
             "title": "Yesterday edition"},
        ]
        for row in examples:
            row.update({"summary": "News summary", "rubric": "news",
                        "cover": "assets/sample.svg",
                        "url": "articles/" + row["id"] + "/"})
        catalog = PUBLISHER.render_catalog(examples)
        positions = [catalog.index('href="' + name + '/"')
                     for name in ("a-late", "z-early", "m-older")]
        self.assertEqual(positions, sorted(positions))
        rss = PUBLISHER.render_feed(examples, "<rss><channel></channel></rss>")
        item_links = [e.findtext("link") for e in
                      ET.fromstring(rss).findall("./channel/item")]
        self.assertEqual([url.rstrip("/").split("/")[-1] for url in item_links],
                         ["a-late", "z-early", "m-older"])

    def test_preflight_never_writes_anything(self):
        prev = {p: p.read_bytes() for p in (self.root / "news.json", self.root / "feed.xml", self.root / "index.html")}
        outputs = PUBLISHER.publish(self.root, "sample-verified-news", apply=False)
        self.assertEqual(len(outputs), 12 + len(TOPICS))
        self.assertFalse((self.root / "articles").exists())
        self.assertFalse((self.root / "sitemap.xml").exists())
        self.assertFalse((self.root / "dzen-rss.xml").exists())
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
        home = (self.root / "index.html").read_text(encoding="utf-8")
        # The homepage spotlights RECENT issues, not an arbitrary historical
        # fixture date. This sample remains in the full articles catalog/RSS.
        self.assertIn('class="home-feature-link"', home)
        self.assertIn("Наши публикации", home)
        self.assertIn("Пример &lt;настоящей&gt; новости", catalog)
        rss = ET.fromstring((self.root / "feed.xml").read_text(encoding="utf-8"))
        self.assertEqual(len(rss.findall("./channel/item")), len(records))
        guid = [x.findtext("guid") for x in rss.findall("./channel/item")
                if x.findtext("link", "").endswith("/google-search-ai-links/")][0]
        self.assertEqual(guid, "https://afterdark1000.github.io/iipike-site/articles/google-search-ai-links/")
        site = ET.fromstring((self.root / "sitemap.xml").read_text(encoding="utf-8"))
        locs = [x.text for x in site.iter() if x.tag.endswith("}loc")]
        self.assertEqual(len(locs), len(records) + 3 + 4 + len(active_topics(records))
                         + len(entity_urls(load_registry(ROOT))))
        self.assertIn("https://iipike.ru/topics/", locs)
        self.assertIn("https://iipike.ru/rubrics/news/", locs)
        self.assertIn("https://iipike.ru/articles/sample-verified-news/", locs)
        self.assertNotIn("drafts/", str(locs))
        with self.assertRaisesRegex(ValueError, "Already published"):
            PUBLISHER.publish(self.root, "sample-verified-news", apply=True)

    def test_full_editor_layout_is_preserved_in_published_html(self):
        self.article["paragraphs"] = [
            {"type": "lead", "text": "В **важной новости** появился *неожиданный* вывод."},
            {"type": "p", "text": "В оригинале есть [документ](https://example.org/paper?part=1&v=2)."},
            {"type": "h2", "text": "Что изменилось"},
            {"type": "ul", "items": ["Первый **факт**", "Второй *факт*"]},
            {"type": "ol", "items": ["Сначала сайт", "Затем Дзен"]},
            {"type": "quote", "text": "Это цитата из <реального> источника.",
             "attribution": "Указанный представитель"},
        ]
        self.write_article()
        page = PUBLISHER.publish(self.root, "sample-verified-news", apply=True)[
            self.root / "articles" / "sample-verified-news" / "index.html"
        ]
        self.assertIn("<strong>важной новости</strong>", page)
        self.assertIn("<em>неожиданный</em>", page)
        self.assertIn('href="https://example.org/paper?part=1&amp;v=2"', page)
        self.assertIn("<h2>Что изменилось</h2>", page)
        self.assertIn('<ul class="editorial-list"><li>Первый <strong>факт</strong></li>', page)
        self.assertIn('<ol class="editorial-list"><li>Сначала сайт</li>', page)
        self.assertIn('<blockquote class="editorial-quote">', page)
        self.assertIn("Это цитата из &lt;реального&gt; источника.", page)
        self.assertIn("<cite>Указанный представитель</cite>", page)
        self.assertLess(page.index("<ul class="), page.index("<ol class="))
        self.assertLess(page.index("<ol class="), page.index("<blockquote class="))

    def test_dzen_bibliography_is_consolidated_in_one_site_source_block(self):
        # The Dzen original must retain all three source links; the site must
        # not repeat the primary source in a second bibliography at the end.
        from scripts.site_rich_text import markdown_to_blocks
        original = (
            "В редакции подтвердили дату события и изучили первоисточники. " * 12
            + "\n\nВторой абзац добавляет подробности проверенного события и его последствий."
            + "\n\n**Первоисточники:**\n\n"
            + "- [Основной источник](https://example.org/source)\n"
            + "- [Дополнительный материал](https://example.org/second)\n"
            + "- [Третий материал](https://example.org/third)"
        )
        self.article["article_markdown"] = original
        self.article["paragraphs"] = markdown_to_blocks(original)
        self.write_article()
        page = PUBLISHER.publish(self.root, "sample-verified-news", apply=True)[
            self.root / "articles" / "sample-verified-news" / "index.html"
        ]
        self.assertEqual(page.count('href="https://example.org/source"'), 1)
        self.assertIn('<summary>Ещё источники (2)</summary>', page)
        self.assertIn('href="https://example.org/second"', page)
        self.assertIn('href="https://example.org/third"', page)
        self.assertNotIn("<strong>Первоисточники:</strong>", page)
        self.assertNotIn('<ul class="editorial-list"><li><a', page)
        self.assertIn("Третий материал", self.article["article_markdown"])
        self.assertEqual(
            PUBLISHER.site_article_sources(self.article["paragraphs"], "https://example.org/source")[0],
            self.article["paragraphs"][:-2],
        )

    def test_site_consolidates_lg_style_sources_with_trailing_punctuation(self):
        from scripts.site_rich_text import markdown_to_blocks
        original = (
            ("Вступительный абзац о новостном событии. " * 12)
            + "\n\nСледующий абзац с объяснением обстоятельств.\n\n"
            + "**Источники:**\n\n"
            "- [Анонс](https://example.org/source).\n"
            "- [Документация](https://example.org/guide).\n"
            "- [Ограничения](https://example.org/limits)."
        )
        blocks = markdown_to_blocks(original)
        kept, extras = PUBLISHER.site_article_sources(blocks, "https://example.org/source")
        self.assertEqual(kept, blocks[:-2])
        self.assertEqual(extras, [
            ("Документация", "https://example.org/guide"),
            ("Ограничения", "https://example.org/limits"),
        ])

    def test_site_consolidates_single_trailing_source_sentence(self):
        from scripts.site_rich_text import markdown_to_blocks
        original = (
            ("Вступительный абзац о новостном событии. " * 12)
            + "\n\nСледующий абзац с объяснением обстоятельств.\n\n"
            + "**Источник:** [Публикация](https://example.org/source)."
        )
        blocks = markdown_to_blocks(original)
        kept, extras = PUBLISHER.site_article_sources(blocks, "https://example.org/source")
        self.assertEqual(kept, blocks[:-1])
        self.assertEqual(extras, [])

    def test_site_keeps_trailing_unrelated_citations_and_lists(self):
        from scripts.site_rich_text import markdown_to_blocks
        originals = [
            "Текст.\n\n**Источники:**\n\n- Простое пояснение.",
            "Текст.\n\nИсточник: редакционный комментарий.",
            "Текст.\n\n**Источник:** [Ссылка](https://example.org/source) и пояснение.",
        ]
        for original in originals:
            original = ("Вступительный абзац о новостном событии. " * 12) + "\n\n" + original
            blocks = markdown_to_blocks(original)
            kept, extras = PUBLISHER.site_article_sources(blocks, "https://example.org/source")
            self.assertEqual(kept, blocks)
            self.assertEqual(extras, [])

    def test_ordinary_end_list_is_not_hidden_as_sources(self):
        blocks = [
            {"type": "p", "text": "**Первоисточники:**"},
            {"type": "ul", "items": ["Ссылка отсутствует", "Обычное перечисление"]},
        ]
        kept, extra = PUBLISHER.site_article_sources(blocks, "https://example.org/source")
        self.assertEqual(kept, blocks)
        self.assertEqual(extra, [])

    def test_unsafe_editorial_inline_link_refuses_publication(self):
        self.article["paragraphs"][1]["text"] = "[Ссылка](javascript:alert(1))"
        self.write_article()
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            PUBLISHER.publish(self.root, "sample-verified-news", apply=True)
        self.assertFalse((self.root / "articles").exists())

    def test_archive_can_omit_unverified_event_date(self):
        self.article.pop("event_date")
        self.write_article()
        outputs = PUBLISHER.publish(self.root, "sample-verified-news", apply=False)
        records = json.loads(outputs[self.root / "news.json"])
        self.assertEqual(records[-1]["id"], "sample-verified-news")
        self.assertNotIn("event_date", records[-1])

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
