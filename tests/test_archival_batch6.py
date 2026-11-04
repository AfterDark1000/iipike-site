"""Regression: Batch 6 maintains original dates, full text, genuine 16:9 artwork."""
import datetime as dt
from pathlib import Path
import json
import html
import re
import unittest
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
EXPECTED={
  "chatgpt-razreshil-pryatat-perepiski-pod-pin-kodom-no-sbrasyvat-8dd8e": "6ad841c15504cd7f3268dd8e",
  "odin-zapros-tselyy-film-videogen-pokazala-kak-ii-samostoyateln-7412a": "6ad83f6c2f47836f3707412a",
  "google-podklyuchila-avtomobilnyy-gemini-k-lichnym-dannym-dcc9d": "6ad83dc546bcf26f507dcc9d",
  "zapishi-menya-k-vrachu-mistral-vypustila-golosovoy-ii-kotoryy-ac376": "6ad8373656a5433cf42ac376",
  "ii-nauchilsya-peredelyvat-mashinnyy-kod-na-khodu-generatsiya-4-dba7d": "6ad8322defbf813a131dba7d",
  "google-otkryla-proekt-ii-protsessora-dlya-chasov-i-datchikov-t-1397a": "6ad8305ababeb53f31a1397a",
  "cloudflare-vypustila-clairic-ii-kotoryy-izvlekaet-dannye-bez-g-bee3a": "6ad74813be108a14528bee3a",
  "openai-ii-nauchilsya-luchshe-rabotat-so-starym-programmnym-kod-11ef5": "6ad747205dd01a7e03411ef5",
  "google-nauchila-gemini-notebook-pokazyvat-plan-video-do-ego-so-37ba9": "6ad73f852d69ac1460137ba9",
  "ii-otkazalsya-lovit-khakerov-79daf": "6ad70dd357450928e2779daf",
  "pyat-minut-video-iz-odnoy-kartinki-kitaytsy-vypustili-omnihuma-73b38": "6ad6f21ca4204c21d6073b38",
  "google-vypustila-instrument-dlya-zapuska-ii-neposredstvenno-na-53169": "6ad6ee4347711c346bf53169",
  "mercury-3-neyroset-kotoraya-pishet-bystree-chem-uspevaesh-chit-5a039": "6ad6eb847b47497b1ee5a039",
  "flux-3-max-desyat-sekund-video-za-dvenadtsat-sekund-ce793": "6ad6eb11fd530f1a039ce793",
  "amazon-uproschaet-zapusk-ii-na-sobstvennykh-protsessorakh-vmes-8c8cf": "6ad63e067fa5c9322f68c8cf",
  "ssha-zapretili-deepseek-v-grazhdanskikh-federalnykh-vedomstvak-ec6b4": "6ad63ced7267ec5b95fec6b4",
  "khaker-ispolzoval-ii-dlya-atak-na-1200-saytov-394c1": "6ad63b1228014a16952394c1",
  "minimax-vypustila-ii-v-tri-raza-bystree-i-na-70-deshevle-4c5d3": "6ad63a9747711c346b04c5d3",
  "tencent-podtverdila-ii-agenty-vyshli-za-ramki-zadaniya-i-nacha-be1ba": "6ad6394a2cdfb474e89be1ba",
  "ii-oboshyol-zaschitu-gosudarstvennogo-sayta-i-poluchil-sekretn-cdbf2": "6ad6385a733b6714e99cdbf2",
  "mask-poobeschal-kazhdomu-rebyonku-ssha-po-aktsii-spacex-tsena-6d4cb": "6ad6025e7e6dd4477fd6d4cb",
  "ii-pronik-vo-vnutrennie-sistemy-issledovatelskoy-organizatsii-1c11d": "6ad5a8f747711c346bd1c11d",
  "anthropic-napravit-5-svoikh-aktsiy-na-obschestvennye-proekty-8c8c1": "6ad5a86b28014a169528c8c1",
  "anthropic-ii-agenty-rabotayut-v-shest-raz-bolshe-chem-sotrudni-5dfab": "6ad5a5d37fa5c9322f45dfab",
  "nvidia-vypustila-noutbuki-dlya-zapuska-moschnogo-ii-bez-oblaka-02c93": "6ad5a483d0db753764002c93",
  "claude-razgadal-25-letnyuyu-zagadku-kriptografii-5c4d6": "6ad5a3da2d69ac1460e5c4d6",
  "deepseek-otkryla-sobstvennyy-poiskovyy-api-9f409": "6ad5a38047711c346bc9f409",
  "deepseek-obnovila-svoyu-otkrytuyu-model-luchshe-pishet-kod-i-b-7bc93": "6ad5a11a53d2e4088607bc93",
  "gpt-6-pro-nauchilsya-raspredelyat-zadachi-mezhdu-neskolkimi-ii-51112": "6ad5a09ebe108a1452e51112",
  "github-zapustil-ii-proverku-bezopasnosti-programmnogo-koda-f93ec": "6ad3433234955e5dfa8f93ec"
}

class Batch6OriginalsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.news=json.loads((ROOT/"news.json").read_text(encoding="utf-8"))
        cls.rows={r["id"]:r for r in cls.news}
        cls.original={r["dzen_id"]:r for r in json.loads(
            (ROOT/"data/editorial_full_catalog_snapshot.json").read_text(encoding="utf-8"))["entries"]}
        p=ROOT/"registry/archive_batch6_sources.json"
        cls.provenance=json.loads(p.read_text(encoding="utf-8"))

    def test_complete_batch_and_no_duplicate_ids(self):
        self.assertEqual(len(EXPECTED),30)
        self.assertGreaterEqual(len(self.news),161)
        self.assertEqual(len(self.news),len({r["url"] for r in self.news}))
        ids=[r.get("dzen_id") for r in self.news if r.get("dzen_id")]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(len(self.provenance["entries"]),30)

    def test_genuine_art_date_and_complete_html(self):
        art={r["slug"]:r for r in self.provenance["entries"]}
        for slug,dzen_id in EXPECTED.items():
            with self.subTest(slug=slug):
                row=self.rows[slug]; src=self.original[dzen_id]; cover=art[slug]
                self.assertEqual(src["url_evidence"],"recorded_in_editorial_archive")
                self.assertEqual(src["title_evidence"],"recorded")
                self.assertEqual(row["dzen_id"],dzen_id)
                self.assertEqual(row["title"],src["title"])
                self.assertEqual(row["dzen_url"],src["dzen_url"])
                when=dt.datetime.fromisoformat(src["published_at_utc"].replace("Z","+00:00"))
                self.assertEqual(row["published_at_utc"],when.strftime("%Y-%m-%dT%H:%M:%SZ"))
                self.assertEqual(row["published"],when.astimezone(ZoneInfo("Asia/Yekaterinburg")).date().isoformat())
                self.assertNotIn("modified_at_utc",row)
                self.assertEqual(row["cover"],cover["cover"])
                self.assertIn(cover["image_source"],("telegram_original_photo","dzen_article_image"))
                self.assertNotIn("get-zen-pub-og",json.dumps(cover))
                if cover["image_source"]=="telegram_original_photo":
                    self.assertTrue(cover["telegram_post"].startswith("https://t.me/iipike/"))
                img=ROOT/row["cover"]
                self.assertTrue(img.is_file(),img)
                self.assertGreater(img.stat().st_size,15000)
                self.assertEqual(img.read_bytes()[:4],b"RIFF")
                self.assertGreaterEqual(cover["width"],780)
                self.assertGreaterEqual(cover["height"],430)
                self.assertGreater(cover["width"]/cover["height"],1.65)
                self.assertLess(cover["width"]/cover["height"],1.86)
                page=(ROOT/row["url"]/"index.html").read_text(encoding="utf-8")
                self.assertIn('rel="canonical" href="https://iipike.ru/'+row["url"]+'"',page)
                self.assertIn('article:published_time" content="'+row["published_at_utc"]+'"',page)
                self.assertIn('"datePublished": "'+row["published_at_utc"]+'"',page)
                self.assertIn(row["dzen_url"],page)
                self.assertNotIn('"dateModified":',page)
                body=page.split('<article class="article-text">',1)[-1].split('</article>',1)[0]
                minimum=430 if dzen_id in {"6ad63ced7267ec5b95fec6b4","6ad63a9747711c346b04c5d3"} else 570
                self.assertGreater(len(html.unescape(re.sub("<[^>]*>"," ",body))),minimum)
                self.assertIn("related-stories",body)

    def test_one_sitemap_url_per_new_article(self):
        xml=ET.parse(ROOT/"sitemap.xml").getroot()
        urls=[e.text for e in xml.iter() if e.tag.endswith("}loc")]
        self.assertGreaterEqual(len(urls),167)
        self.assertEqual(len(urls),len(set(urls)))
        for slug in EXPECTED:
            self.assertEqual(urls.count("https://iipike.ru/"+self.rows[slug]["url"]),1)

if __name__=="__main__":
    unittest.main()
