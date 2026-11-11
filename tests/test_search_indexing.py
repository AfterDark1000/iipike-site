"""Search indexing regression checks for iipike.ru (offline, no publication)."""
import json
import re
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from scripts.site_rubrics import populated
from scripts.site_topics import active_topics
from scripts.site_entities import entity_urls, load_registry

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://iipike.ru"
NAMESPACE = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


class SearchIndexingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.records = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
        cls.feed = (ROOT / "feed.xml").read_text(encoding="utf-8")

    def test_domain_and_home_metadata(self):
        self.assertEqual((ROOT / "CNAME").read_text(encoding="utf-8").strip(), "iipike.ru")
        self.assertIn('<link rel="canonical" href="https://iipike.ru/">', self.home)
        self.assertIn('<meta property="og:url" content="https://iipike.ru/">', self.home)
        self.assertIn('https://iipike.ru/assets/google-search-links.svg', self.home)
        self.assertNotIn('https://afterdark1000.github.io/iipike-site/', self.home)

    def test_sitemap_only_has_real_reviewed_site_pages(self):
        tree = ET.parse(ROOT / "sitemap.xml")
        urls = [p.text for p in tree.findall(".//s:loc", NAMESPACE)]
        expected = ([BASE + "/", BASE + "/articles/"] +
                    [BASE + "/rubrics/" + key + "/" for key in populated(self.records)] +
                    ([BASE + "/topics/"] +
                     [BASE + "/topics/" + key + "/" for key in active_topics(self.records)]
                     if (ROOT / "topics" / "index.html").is_file() else []) +
                    entity_urls(load_registry(ROOT)) +
                    [BASE + "/" + row["url"] for row in self.records])
        self.assertEqual(urls, expected)
        self.assertEqual(len(urls), len(set(urls)))
        for url in urls:
            self.assertTrue(url.startswith(BASE + "/"), url)
            self.assertNotIn("/drafts/", url)
            self.assertNotIn("/registry/", url)
            self.assertNotIn("dzen.ru", url)
        for row in self.records:
            html_path = ROOT / row["url"] / "index.html"
            self.assertTrue(html_path.exists(), html_path)
            html = html_path.read_text(encoding="utf-8")
            self.assertIn(f'rel="canonical" href="{BASE}/{row["url"]}"', html)
            self.assertIn(f'property="og:url" content="{BASE}/{row["url"]}"', html)
            self.assertNotIn('https://afterdark1000.github.io/iipike-site/', html)
            self.assertNotIn('name="robots" content="noindex', html.lower())

    def test_drafts_and_registry_stay_noindex(self):
        pages = list((ROOT / "drafts").glob("*/index.html"))
        self.assertGreater(len(pages), 0, "Expected labelled draft previews")
        pages.extend([ROOT / "drafts/index.html", ROOT / "registry/index.html"])
        for p in pages:
            self.assertIn('name="robots" content="noindex, nofollow"', p.read_text(encoding="utf-8"), str(p))

    def test_related_card_lab_is_a_nonindexed_isolated_article_copy(self):
        original = (ROOT / "articles" / "alex-stamos-ai-cybersecurity-dark-age-20261107" /
                    "index.html").read_text(encoding="utf-8")
        inline = (ROOT / "lab" / "related-card" / "index.html").read_text(encoding="utf-8")
        fallback = (ROOT / "lab" / "related-card" / "fallback" /
                    "index.html").read_text(encoding="utf-8")
        article_url = 'https://iipike.ru/articles/censys-artex-exposed-servers-20261105/'
        cover_file = (ROOT / "assets" / "editorial" /
                      "censys-artex-exposed-servers-20261105.webp")
        self.assertTrue(cover_file.is_file())
        for html in (inline, fallback):
            self.assertIn('<meta name="robots" content="noindex,nofollow,noarchive">', html)
            self.assertNotIn('rel="canonical"', html)
            self.assertNotIn('application/ld+json', html)
            self.assertNotIn('property="og:url"', html)
            self.assertEqual(html.count('<a class="lab-related-card"'), 1)
            self.assertIn('Цена токена для атакующих стремится к нулю', html)
            self.assertIn(f'href="{article_url}"', html)
            self.assertIn('class="lab-related-card-eyebrow">По теме</span>', html)
            self.assertNotIn('По теме · ХПИИ', html)
            self.assertIn('font:700 16px/1.42', html)
        self.assertIn(
            'src="../../assets/editorial/censys-artex-exposed-servers-20261105.webp"',
            inline,
        )
        self.assertIn(
            'src="../../../assets/editorial/censys-artex-exposed-servers-20261105.webp"',
            fallback,
        )
        self.assertIn('href="fallback/">Без ссылок редактора</a>', inline)
        self.assertIn('href="../">В тексте</a>', fallback)
        self.assertNotIn("https://dzen.ru/a/", fallback)
        self.assertNotIn('class="related-stories"', fallback)
        self.assertLess(
            inline.index('class="lab-related-card"'),
            inline.index('Как защищаться, если нападать становится дешевле'),
        )
        self.assertGreater(
            fallback.index('class="lab-related-card"'),
            fallback.index('Пока же, по оценке Стамоса, нападающие'),
        )
        self.assertNotIn('class="lab-related-card"', original)
        self.assertNotIn("/lab/related-card/", (ROOT / "sitemap.xml").read_text())
        self.assertNotIn("/lab/related-card/", self.feed)
        self.assertTrue(all("/lab/related-card/" not in row.get("url", "")
                            for row in self.records))

    def test_robots_and_rss_use_primary_domain(self):
        robots = (ROOT / "robots.txt").read_text(encoding="utf-8")
        self.assertIn("Sitemap: https://iipike.ru/sitemap.xml", robots)
        self.assertNotIn("Disallow: /", robots)
        self.assertIn("<link>https://iipike.ru/</link>", self.feed)
        self.assertIn("<link>https://iipike.ru/articles/google-search-ai-links/</link>", self.feed)
        # An existing RSS item's GUID must not change when changing hosting domains.
        self.assertIn('<guid isPermaLink="true">https://afterdark1000.github.io/iipike-site/articles/google-search-ai-links/</guid>', self.feed)

    def test_sitemap_generation_is_up_to_date(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_sitemap.py"), "--check"],
            cwd=ROOT, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
