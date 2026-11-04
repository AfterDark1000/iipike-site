"""Final archive batch8: exactly 218 historical Dzen originals plus the pilot."""
import hashlib,json,unittest
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
class FinalArchiveIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.news=json.loads((ROOT/"news.json").read_text(encoding="utf-8"))
        cls.catalog=json.loads((ROOT/"data/editorial_full_catalog_snapshot.json").read_text(encoding="utf-8"))["entries"]
        cls.final=json.loads((ROOT/"registry/archive_batch8_sources.json").read_text(encoding="utf-8"))
        cls.by_id={e.get("dzen_id"):e for e in cls.news if e.get("dzen_id")}
        cls.meta={e["dzen_id"]:e for e in cls.catalog}
    def test_full_legacy_catalog_has_no_missing_or_duplicate_original(self):
        ids=[x["dzen_id"] for x in self.news if x.get("dzen_id")]
        self.assertEqual(len(self.catalog),218)
        self.assertEqual(len(self.news),219)
        self.assertEqual(len(ids),218)
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(set(ids),set(self.meta))
        self.assertEqual(self.final["prepared"],28)
        self.assertEqual(self.final["remaining"],0)
        self.assertEqual(self.final["historical_catalog"],218)
        self.assertEqual(self.final["previous_public"],191)
        self.assertEqual(len(self.final["entries"]),28)
        self.assertEqual(self.final["historical_exact_time"],3)
        self.assertEqual(self.final["day_only"],25)
    def test_all_final_originals_are_authentic_and_no_branded_sharecards(self):
        for item in self.final["entries"]:
            with self.subTest(item=item["slug"]):
                catalog=self.meta[item["dzen_id"]]
                row=self.by_id[item["dzen_id"]]
                self.assertEqual(catalog["title"],item["title"])
                self.assertEqual(catalog["dzen_url"],item["dzen_url"])
                self.assertEqual(catalog["published_date"],item["published"])
                self.assertEqual(catalog["published_date_evidence"],"dzen_itemprop_datePublished")
                self.assertEqual(catalog["title_evidence"],"verified_on_public_dzen_page")
                self.assertEqual(catalog["url_evidence"],"verified_on_public_dzen_page")
                self.assertEqual(row["id"],item["slug"])
                self.assertEqual(row["title"],item["title"])
                self.assertEqual(row["published"],item["published"])
                self.assertEqual(row["cover"],item["cover"])
                self.assertEqual(item["dzen_url"],row["dzen_url"])
                art=ROOT/item["cover"]
                self.assertTrue(art.is_file())
                self.assertGreater(art.stat().st_size,15000)
                self.assertEqual(art.read_bytes()[:4],b"RIFF")
                self.assertEqual(hashlib.sha256(art.read_bytes()).hexdigest(),item["artwork_sha256"])
                self.assertGreaterEqual(item["artwork_width"],780)
                self.assertGreaterEqual(item["artwork_height"],430)
                self.assertGreater(item["artwork_width"]/item["artwork_height"],1.65)
                self.assertLess(item["artwork_width"]/item["artwork_height"],1.86)
                self.assertNotIn("get-zen-pub-og",item["artwork_source_url"])
                self.assertIn(item["artwork_source_type"],
                              ("telegram_original_photo","dzen_article_original_native_crop","dzen_article_image"))
                pg=ROOT/row["url"]/"index.html"
                self.assertTrue(pg.is_file())
                html=pg.read_text(encoding="utf-8")
                self.assertIn('rel="canonical" href="https://iipike.ru/'+row["url"]+'"',html)
                self.assertIn(item["dzen_url"],html)
                self.assertIn('class="article-text"',html)
                self.assertNotIn('"dateModified":',html)
                if item["publication_date_precision"]=="day":
                    self.assertNotIn("published_at_utc",row)
                    self.assertNotIn('property="article:published_time"',html)
                    self.assertIn('"datePublished": "'+item["published"]+'"',html)
                else:
                    self.assertEqual(row["published_at_utc"],item["published_at_utc"])
                    self.assertIn('article:published_time" content="'+item["published_at_utc"]+'"',html)
                    self.assertIn('"datePublished": "'+item["published_at_utc"]+'"',html)
                minimum=375 if item["dzen_id"]=="6acc57b80e28a620956e111e" else 500
                self.assertGreaterEqual(item["source_full_text_characters"],minimum)
    def test_sitemap_and_rss_complete_without_fabricating_times(self):
        tree=ET.parse(ROOT/"sitemap.xml").getroot()
        urls=[x.text for x in tree.iter() if x.tag.endswith("}loc")]
        self.assertEqual(len(urls),225)
        self.assertEqual(len(set(urls)),len(urls))
        feed=ET.parse(ROOT/"feed.xml").getroot()
        items={x.findtext("link"):x for x in feed.findall("./channel/item")}
        for article in self.final["entries"]:
            u="https://iipike.ru/articles/"+article["slug"]+"/"
            self.assertEqual(urls.count(u),1)
            self.assertIn(u,items)
            if article["publication_date_precision"]=="day":
                self.assertIsNone(items[u].find("pubDate"))
            else:
                self.assertIsNotNone(items[u].find("pubDate"))
if __name__=="__main__":
    unittest.main()
