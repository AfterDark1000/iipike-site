"""Historical archive batch7: 30 authentic Dzen day-only articles, no fabricated times."""
import hashlib
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]

class SeventhBatchIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog={x["dzen_id"]:x for x in json.loads((ROOT/"data/editorial_full_catalog_snapshot.json").read_text(encoding="utf-8"))["entries"]}
        cls.news=json.loads((ROOT/"news.json").read_text(encoding="utf-8"))
        cls.registry=json.loads((ROOT/"registry/archive_batch7_sources.json").read_text(encoding="utf-8"))
        cls.by_id={x.get("dzen_id"):x for x in cls.news if x.get("dzen_id")}
    def test_thirty_original_articles_and_unique_dzen_ids(self):
        records=self.registry["entries"]
        self.assertEqual(self.registry["selected_count"],30)
        self.assertEqual(len(records),30)
        self.assertGreaterEqual(len(self.news),191)
        self.assertGreaterEqual(len({x.get("dzen_id") for x in self.news if x.get("dzen_id")}),190)
        self.assertEqual(len({x["dzen_id"] for x in records}),30)
        self.assertEqual(len({x["slug"] for x in records}),30)
    def test_original_title_day_date_and_page_without_fabricated_seconds(self):
        for entry in self.registry["entries"]:
            with self.subTest(slug=entry["slug"]):
                source=self.catalog[entry["dzen_id"]]
                self.assertEqual(source["title_evidence"],"verified_on_public_dzen_page")
                self.assertEqual(source["url_evidence"],"verified_on_public_dzen_page")
                self.assertEqual(source["published_date_evidence"],"dzen_itemprop_datePublished")
                self.assertEqual(source["published_date"],entry["published"])
                self.assertEqual(source["title"],entry["title"])
                self.assertEqual(source["dzen_url"],entry["dzen_url"])
                record=self.by_id[entry["dzen_id"]]
                self.assertEqual(record["id"],entry["slug"])
                self.assertEqual(record["title"],entry["title"])
                self.assertEqual(record["published"],entry["published"])
                self.assertEqual(record["publication_date_precision"],"day")
                self.assertNotIn("published_at_utc",record)
                self.assertNotIn("modified_at_utc",record)
                self.assertEqual(record["cover"],entry["cover"])
                self.assertGreaterEqual(entry["artwork_width"],780)
                self.assertGreaterEqual(entry["artwork_height"],430)
                self.assertGreater(entry["artwork_width"]/entry["artwork_height"],1.65)
                self.assertLess(entry["artwork_width"]/entry["artwork_height"],1.86)
                self.assertNotIn("get-zen-pub-og",entry["image_url_source"])
                artwork=ROOT/entry["cover"]
                self.assertTrue(artwork.is_file())
                self.assertGreater(artwork.stat().st_size,15000)
                self.assertEqual(artwork.read_bytes()[:4],b"RIFF")
                self.assertEqual(hashlib.sha256(artwork.read_bytes()).hexdigest(),entry["sha256"])
                page=(ROOT/record["url"]/"index.html").read_text(encoding="utf-8")
                self.assertIn('rel="canonical" href="https://iipike.ru/'+record["url"]+'"',page)
                self.assertIn('"datePublished": "'+record["published"]+'"',page)
                self.assertNotIn('property="article:published_time"',page)
                self.assertNotIn('"dateModified":',page)
                self.assertIn(entry["dzen_url"],page)
                self.assertIn('class="article-text"',page)
                self.assertIn('rel="noopener noreferrer"',page)
                self.assertGreater(entry["source_full_text_characters"],500)
    def test_sitemap_and_rss_do_not_invent_dates(self):
        xml=ET.parse(ROOT/"sitemap.xml").getroot()
        urls=[x.text for x in xml.iter() if x.tag.endswith("}loc")]
        self.assertGreaterEqual(len(urls),197)
        self.assertEqual(len(urls),len(set(urls)))
        feed=ET.parse(ROOT/"feed.xml").getroot()
        items={x.findtext("link"):x for x in feed.findall("./channel/item")}
        for record in self.registry["entries"]:
            u="https://iipike.ru/articles/"+record["slug"]+"/"
            self.assertEqual(urls.count(u),1)
            self.assertIn(u,items)
            self.assertIsNone(items[u].find("pubDate"),"Missing original time may not be simulated")
if __name__=="__main__":
    unittest.main()
