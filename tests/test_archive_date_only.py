"""Verified date-only archive publication: no synthetic UTC time, no date duplication."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from scripts.publish_approved_article import approved_article,render_article,render_feed
from scripts.site_related import verified

class HistoricalDateOnlyTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.id="6ad342fc8da7ee4d90019cef"
        url="https://dzen.ru/a/"+base64.urlsafe_b64encode(bytes.fromhex(self.id)).decode().rstrip("=")
        self.entry={
            "dzen_id":self.id,"dzen_url":url,"title":"Проверенный исторический материал",
            "published_date":"2026-10-17",
            "published_date_evidence":"dzen_itemprop_datePublished",
            "title_evidence":"verified_on_public_dzen_page",
            "url_evidence":"verified_on_public_dzen_page"}
        self.data={"slug":"test-historic-date","status":"approved","approved_by":"Редакция ХПИИ",
            "approved_at":"2026-11-04","title":self.entry["title"],"summary":"Проверенный длинный текст о новостном сюжете","published":"2026-10-17",
            "publication_date_precision":"day","rubric":"news","section":"ИСТОРИЧЕСКИЙ АРХИВ",
            "source_url":url,"source_title":"ХПИИ — исходная публикация в Дзене",
            "cover":"assets/imported/verified.webp","dzen_id":self.id,"dzen_url":url,
            "paragraphs":[{"type":"lead","text":"Оригинальный первый абзац."},
                          {"type":"p","text":"Исходная история продолжена в следующем абзаце."}]}
        p=self.root/"data/editorial_full_catalog_snapshot.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"schema_version":1,"entries":[self.entry]}))
        p=self.root/"content/approved/test-historic-date.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(self.data,ensure_ascii=False))
        p=self.root/"assets/imported/verified.webp"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"RIFF_WEBP_fixture")

    def persist(self):
        p=self.root/"data/editorial_full_catalog_snapshot.json"
        p.write_text(json.dumps({"schema_version":1,"entries":[self.entry]},ensure_ascii=False))
        p=self.root/"content/approved/test-historic-date.json"
        p.write_text(json.dumps(self.data,ensure_ascii=False))

    def test_real_dzen_day_without_invented_timestamp(self):
        self.assertTrue(verified(self.entry))
        info=approved_article(self.root,self.data["slug"])
        self.assertNotIn("published_at_utc",info)
        page=render_article(info)
        self.assertIn('datePublished": "2026-10-17"',page)
        self.assertIn("Опубликовано: 17 октября 2026",page)
        self.assertNotIn("article:published_time",page)
        self.assertNotIn('2026-10-17T00:00',page)
        self.assertNotIn('dateModified',page)

    def test_requires_authentic_date_evidence_and_exact_day(self):
        self.entry["published_date_evidence"]="inferred_from_id"
        self.persist()
        with self.assertRaises(ValueError): approved_article(self.root,self.data["slug"])
        self.entry["published_date_evidence"]="dzen_itemprop_datePublished"
        self.data["published"]="2026-10-16"
        self.persist()
        with self.assertRaises(ValueError): approved_article(self.root,self.data["slug"])
        self.data["published"]="2026-10-17"
        self.data["published_at_utc"]="2026-10-17T00:00:00Z"
        self.persist()
        with self.assertRaises(ValueError): approved_article(self.root,self.data["slug"])

    def test_rss_omits_pubdate_instead_of_forging_clock_time(self):
        rows=[{"id":"test-historic-date","url":"articles/test-historic-date/",
               "title":self.data["title"],"summary":self.data["summary"],
               "published":"2026-10-17","rubric":"news"}]
        xml=render_feed(rows,'<?xml version="1.0"?><rss><channel></channel></rss>')
        root=ET.fromstring(xml)
        item=root.find("./channel/item")
        self.assertIsNotNone(item)
        self.assertIsNone(item.find("pubDate"))
        self.assertIn("<description>",xml)

    def test_bad_title_url_evidence_never_promoted(self):
        self.entry["url_evidence"]="derived_from_12_byte_id"
        self.persist()
        self.assertFalse(verified(self.entry))
        with self.assertRaises(ValueError):approved_article(self.root,self.data["slug"])
if __name__=="__main__":
    unittest.main()
