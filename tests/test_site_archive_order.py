"""First-party article listings must share one time-based chronology."""
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

from scripts.site_home import sorted_published

ROOT = Path(__file__).resolve().parents[1]


class FirstPartyChronologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
        cls.expected = [row["id"] for row in sorted_published(cls.records)]

    def test_all_materials_page_uses_actual_publication_utc(self):
        html = (ROOT / "articles" / "index.html").read_text(encoding="utf-8")
        ids = re.findall(r'<a class="archive-card" href="([^"/]+)/">', html)
        self.assertEqual(len(ids), len(self.records))
        self.assertEqual(ids, self.expected)

    def test_public_rss_order_matches_the_site_archive(self):
        xml = ET.fromstring((ROOT / "feed.xml").read_text(encoding="utf-8"))
        urls = [item.findtext("link") for item in xml.findall("./channel/item")]
        slugs = [url.rstrip("/").split("/")[-1] for url in urls]
        self.assertEqual(slugs, self.expected)

    def test_big_home_cover_is_never_cropped(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "assets/site.css").read_text(encoding="utf-8")
        self.assertEqual(html.count('class="home-feature-image"'), 1)
        self.assertIn('style="--feature-art:url(&quot;assets/', html)
        rules = css.split(".home-feature-image img{", 1)[1].split("}", 1)[0]
        self.assertIn("object-fit:contain", rules)
        self.assertNotIn("object-fit:cover", rules)
        self.assertIn("background-image:var(--feature-art)", css)


if __name__ == "__main__":
    unittest.main()
