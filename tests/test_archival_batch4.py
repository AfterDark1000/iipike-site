"""Regression for the fourth HPII Dzen archive import: no forged dates or covers."""
from pathlib import Path
from zoneinfo import ZoneInfo
import datetime as dt
import html
import json
import re
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
EXPECTED={
  "claude-uvolnyaet-ii-agentov-cf215": "6ae07e9d388b67714d9cf215",
  "nvidia-nauchila-ii-servery-chinit-sebya-dazhe-slomannaya-vi-34bad": "6ae065e0e9368d4a2d734bad",
  "gpt-6-1-terra-ot-openai-obognala-flagmana-vtroe-bystree-i-v-fb75b": "6ae062a4621e6a2e9f1fb75b",
  "chatgpt-pashet-na-165-frontah-openai-raskryla-chem-ego-nagr-12612": "6ae060ef3404d230ff312612",
  "anthropic-ostanovila-obuchenie-novogo-ii-bolshe-chem-na-mes-21ad9": "6ae0522ce601f329d6421ad9",
  "nvidia-i-cadence-posadili-ii-za-chertezhi-mikroshem-b3793": "6ae049b399791f7d2c3b3793",
  "meta-ischet-95-mlrd-na-ii-dazhe-nvidia-prismatrivaetsya-8b82a": "6ae0485408dabf010518b82a",
  "anthropic-sobralas-na-birzhu-tsena-voprosa-trilliony-12e5c": "6ae0447e63b27e51e1c12e5c",
  "v-openai-nashli-sposob-skryvat-sotni-deystviy-ii-ot-sistemy-65e1d": "6ae040ace9368d4a2d265e1d",
  "kitaytsy-otkryli-ii-giganta-na-744-milliarda-9a73c": "6adf2f42f8edfc31bb69a73c",
  "tencent-vypustila-videomir-kotoryy-slushaetsya-komand-bebef": "6adf28bce17db653337bebef",
  "kitaytsy-vylozhili-ii-na-33-milliarda-parametrov-potyanesh-6cd23": "6adf2634edeaf11d1f76cd23",
  "ollama-nauchilas-ozvuchivat-lokalnye-neyroseti-b31ee": "6adee4d2397db6616bdb31ee",
  "claude-gotovil-ataki-grok-sobiral-paroli-kak-rabotala-haker-0e7e6": "6addff2a38340e44ed00e7e6",
  "mask-protiv-nolana-grok-vypustil-pervye-7-minut-svoey-odiss-d94a0": "6add811297126b54779d94a0",
  "kitayskaya-iflytek-nauchila-ii-delit-rabotu-mezhdu-pk-i-obl-0e95c": "6adcb98a40c3ad0e7f80e95c",
  "openai-otklyuchila-gpt-4-gpt-3-5-i-drugie-starye-modeli-v-a-14aaa": "6adc71cd3e43c31ff1214aaa",
  "openai-razreshila-ii-agentam-samostoyatelno-naznachat-sebe-e18bb": "6adc7113b5289f5e98ae18bb",
  "13-neyrosetey-horom-nazvali-lyudey-litsemerami-6cd80": "6adc52faf8edfc31bb76cd80",
  "durov-sobiraet-chatgpt-claude-i-grok-v-telegram-0d3d4": "6adc5238e601f329d6d0d3d4",
  "ii-openai-nashyol-lazeyku-v-internet-obuchenie-moschneyshih-b167d": "6adc5171e6b18e075bdb167d",
  "claude-pytalsya-podsunut-vredonosnyy-kod-nastoyaschim-razra-ff095": "6adc4f90e17db653330ff095",
  "kimi-k3-1-pro-pochti-dognala-claude-opus-5-5-a3934": "6adc4eefedeaf11d1f7a3934",
  "1-000-000-na-knigah-s-ii-pisatelnitsa-iz-yuar-vypustila-371-1cdaf": "6adc4df03404d230ff51cdaf",
  "canva-vypustila-sobstvennuyu-neyroset-4b186": "6adc4d61be6dfd538d14b186",
  "hakery-s-claude-code-vzlomali-ne-menee-15-meditsinskih-orga-083c3": "6adc4b7fbefc9746e6b083c3",
  "aws-vypustila-ii-remontnika-sam-ischet-dyry-v-kode-i-prinos-28700": "6adb35c595e73b66d2f28700",
  "hugging-face-nauchila-ii-chitat-dnk-genetikam-teper-est-s-k-f6dca": "6adb353063b27e51e1ff6dca",
  "ii-microsoft-oboshyol-vrachey-v-diagnostike-slozhnyh-zabole-f8729": "6adb3061621e6a2e9fef8729",
  "les-ischez-no-sputniki-vsyo-pomnyat-ii-nauchili-otslezhivat-73085": "6adb2d2f97126b5477f73085"
} 

class Batch4IntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows=json.loads((ROOT/"news.json").read_text(encoding="utf-8"))
        cls.rows={r["id"]:r for r in rows}
        cls.all_rows=rows
        cls.catalog={x["dzen_id"]:x for x in json.loads(
            (ROOT/"data/editorial_full_catalog_snapshot.json").read_text(encoding="utf-8"))["entries"]}

    def test_complete_and_no_duplicates(self):
        self.assertEqual(len(EXPECTED),30)
        self.assertGreaterEqual(len(self.all_rows),101)
        self.assertEqual(len(self.all_rows),len({x["url"] for x in self.all_rows}))
        source_ids=[x.get("dzen_id") for x in self.all_rows if x.get("dzen_id")]
        self.assertEqual(len(source_ids),len(set(source_ids)))

    def test_original_publication_timestamps_and_titles(self):
        for slug, source_id in EXPECTED.items():
            with self.subTest(slug=slug):
                r=self.rows[slug]
                original=self.catalog[source_id]
                self.assertEqual(original["url_evidence"],"recorded_in_editorial_archive")
                self.assertEqual(original["title_evidence"],"recorded")
                self.assertEqual(r["dzen_id"],source_id)
                self.assertEqual(r["title"],original["title"])
                self.assertEqual(r["dzen_url"],original["dzen_url"])
                a=dt.datetime.fromisoformat(r["published_at_utc"].replace("Z","+00:00"))
                b=dt.datetime.fromisoformat(original["published_at_utc"].replace("Z","+00:00"))
                self.assertEqual(a,b)
                self.assertEqual(r["published"],a.astimezone(ZoneInfo("Asia/Yekaterinburg")).date().isoformat())
                self.assertNotIn("modified_at_utc",r,"Do not invent an update during migration")

    def test_original_article_html_and_cover(self):
        for slug in EXPECTED:
            with self.subTest(slug=slug):
                r=self.rows[slug]
                artwork=ROOT/r["cover"]
                self.assertTrue(artwork.is_file(),r["cover"])
                self.assertGreater(artwork.stat().st_size,15000)
                self.assertEqual(artwork.read_bytes()[:4],b"RIFF")
                page=(ROOT/r["url"]/"index.html").read_text(encoding="utf-8")
                self.assertIn('rel="canonical" href="https://iipike.ru/'+r["url"]+'"',page)
                self.assertIn('article:published_time" content="'+r["published_at_utc"]+'"',page)
                self.assertIn('"datePublished": "'+r["published_at_utc"]+'"',page)
                self.assertNotIn('"dateModified":',page)
                self.assertNotIn("На сайте:",page)
                self.assertIn(r["dzen_url"],page)
                body=page.split('<article class="article-text">',1)[-1].split('</article>',1)[0]
                self.assertGreater(len(html.unescape(re.sub("<[^>]*>"," ",body))),570)

    def test_sitemap_contains_exactly_one_url_per_imported_article(self):
        root=ET.parse(ROOT/"sitemap.xml").getroot()
        urls=[e.text for e in root.iter() if e.tag.endswith("}loc")]
        self.assertEqual(len(urls),len(set(urls)))
        for slug in EXPECTED:
            self.assertEqual(urls.count("https://iipike.ru/"+self.rows[slug]["url"]),1)

if __name__=="__main__":
    unittest.main()
