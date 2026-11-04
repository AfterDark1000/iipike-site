"""Historical HPII transfer regression: preserve original Dzen dates and art."""
import datetime as dt
from html import unescape
import json
from pathlib import Path
import re
import unittest
from zoneinfo import ZoneInfo
from scripts.site_related import verified

ROOT=Path(__file__).resolve().parents[1]

class HistoricalArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.news=json.loads((ROOT/"news.json").read_text(encoding="utf-8"))
        cls.archive={r["dzen_id"]:r for r in json.loads(
            (ROOT/"data/editorial_full_catalog_snapshot.json").read_text(encoding="utf-8")
        )["entries"]}
        cls.migrated=[x for x in cls.news if x.get("dzen_id")]

    def test_all_originals_are_distinct_and_verified(self):
        self.assertGreaterEqual(len(self.migrated),40,"40 archived Dzen articles expected")
        self.assertEqual(len(self.migrated),len({x["dzen_id"] for x in self.migrated}))
        self.assertEqual(len(self.news),len({x["url"] for x in self.news}))
        for row in self.migrated:
            source=self.archive[row["dzen_id"]]
            self.assertTrue(verified(source),"Only original archive or verified Dzen page provenance is allowed")
            self.assertEqual(source["dzen_url"],row["dzen_url"])
            self.assertEqual(source["title"],row["title"])

    def test_original_date_never_replaced_by_migration_date(self):
        for row in self.migrated:
            source=self.archive[row["dzen_id"]]
            page=(ROOT/row["url"]/"index.html").read_text(encoding="utf-8")
            if row.get("publication_date_precision")=="day":
                self.assertNotIn("published_at_utc",row)
                self.assertEqual(source.get("published_date_evidence"),"dzen_itemprop_datePublished")
                self.assertEqual(row["published"],source["published_date"],row["id"])
                self.assertIn('"datePublished": "'+row["published"]+'"',page)
                self.assertNotIn('property="article:published_time"',page)
                self.assertNotIn('T00:00:00Z',page)
            else:
                actual=dt.datetime.fromisoformat(row["published_at_utc"].replace("Z","+00:00"))
                archived=dt.datetime.fromisoformat(source["published_at_utc"].replace("Z","+00:00"))
                self.assertEqual(actual,archived,row["id"])
                self.assertEqual(
                    row["published"],actual.astimezone(ZoneInfo("Asia/Yekaterinburg")).date().isoformat(),
                    row["id"],
                )
                self.assertIn('article:published_time" content="'+row["published_at_utc"]+'"',page)
                self.assertIn('"datePublished": "'+row["published_at_utc"]+'"',page)
            self.assertNotIn("На сайте:",page)
            self.assertNotIn("Первоначально опубликовано в Дзене:",page)

    def test_original_art_and_full_html_are_present(self):
        self.assertGreaterEqual(len(self.migrated),40)
        for row in self.migrated:
            cover=ROOT/row["cover"]
            self.assertTrue(cover.is_file(),f"Original artwork missing: {row['id']}")
            self.assertGreater(cover.stat().st_size,15000,f"Artwork too small: {row['id']}")
            self.assertEqual(cover.read_bytes()[:4],b"RIFF",f"Not original WebP copy: {row['id']}")
            page=(ROOT/row["url"]/"index.html").read_text(encoding="utf-8")
            self.assertIn(row["cover"],page)
            self.assertIn("article-text",page)
            self.assertIn(row["dzen_url"],page)
            body=page.split('<article class="article-text">',1)[-1].split('</article>',1)[0]
            without_tags=unescape(re.sub(r"<[^>]+>"," ",body))
            self.assertGreater(len(without_tags),550,f"Full text too short: {row['id']}")

if __name__=="__main__":
    unittest.main()
