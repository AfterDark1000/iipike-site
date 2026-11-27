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

    def test_big_home_cover_uses_natural_proportions_without_letterboxing(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "assets/site.css").read_text(encoding="utf-8")
        self.assertEqual(html.count('class="home-feature-image"'), 1)
        self.assertIn('<div class="home-feature-image">', html)
        self.assertNotIn('--feature-art', html)
        self.assertNotIn('background-image:var(--feature-art)', css)
        rules = css.split(".home-feature-image img{", 1)[1].split("}", 1)[0]
        self.assertIn("aspect-ratio:16/9", rules)
        self.assertIn("height:auto", rules)
        self.assertIn("object-fit:contain", rules)

    def test_archive_cards_put_headline_before_metadata_and_summary(self):
        html = (ROOT / "articles" / "index.html").read_text(encoding="utf-8")
        cards = re.findall(r'<a class="archive-card".*?</a>', html)
        self.assertEqual(len(cards), len(self.records))
        for card in cards:
            self.assertLess(card.index('<h3>'), card.index('<small class="date">'))
            self.assertLess(card.index('<small class="date">'), card.index('<p>'))


    def test_archive_matches_generator_and_uses_real_local_dates(self):
        from itertools import groupby
        from scripts.publish_approved_article import render_catalog
        from scripts.site_rubrics import publication_label, RUBRICS
        html = (ROOT / "articles/index.html").read_text(encoding="utf-8")
        records = sorted_published(self.records)
        self.assertEqual(html, render_catalog(records))
        labels = [publication_label(r) for r in records]
        days = [day for day, _ in groupby(labels, key=lambda v: v.partition(" · ")[0])]
        self.assertEqual(re.findall(r'<h2 class="rubric-day-title">(.*?)</h2>', html), days)
        self.assertEqual(re.findall(r'<span class="rubric-time" aria-label="([^"]+)">([^<]*)</span>', html),
                         [(label, label.partition(" · ")[2]) for label in labels])
        self.assertEqual(re.findall(r'<span class="archive-rubric" data-rubric="([^"]+)">([^<]*)</span>', html),
                         [(r.get("rubric", "news"), RUBRICS[r.get("rubric", "news")]["name"]) for r in records])
        self.assertIn(f"Материалов: {len(records)}", html)
        self.assertIn('class="home-v1 rubric-r2 archive-r2"', html)


if __name__ == "__main__":
    unittest.main()
