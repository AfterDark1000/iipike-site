"""Regression for Batch 5 original Dzen texts, dates, and own article covers."""
import datetime as dt
import html
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
EXPECTED={
    "ii-puzyr-treschit-po-shvam-aktsii-intel-rukhnuli-na-29-alphabe-b23d3": "6ae981bb5ec3a00a555b23d3",
    "ii-puzyr-v-kitae-lopnul-za-chetyre-mesyatsa-isparilis-480-mill-74d9e": "6ae0a6d4eedc244b0da74d9e",
    "claude-uvolnyaet-ii-agentov-cf215": "6ae07e9d388b67714d9cf215",
    "nvidia-nauchila-ii-servery-chinit-sebya-dazhe-slomannaya-video-34bad": "6ae065e0e9368d4a2d734bad",
    "gpt-6-1-terra-ot-openai-obognala-flagmana-vtroe-bystree-i-v-de-fb75b": "6ae062a4621e6a2e9f1fb75b",
    "chatgpt-pashet-na-165-frontakh-openai-raskryla-chem-ego-nagruz-12612": "6ae060ef3404d230ff312612",
    "13-neirosetei-khorom-nazvali-lyudei-litsemerami-6cd80": "6adc52faf8edfc31bb76cd80",
    "ibm-nauchila-ii-slushat-bez-oblaka-russkii-poka-ne-vyuchila-824cf": "6adb25b2edeaf11d1f8824cf",
    "elevenlabs-vypustila-dvukh-golosovykh-ii-odin-deshevle-drugoi-9e83d": "6adb058c3404d230ff39e83d",
    "elevenlabs-predstavila-perevodchik-kotoryi-pozvolyaet-razgovar-635c7": "6adb03623404d230ff3635c7",
    "khakery-s-ii-atakovali-bolee-2250-oblachnykh-sred-microsoft-36-5ef27": "6adaf7c0f8edfc31bb35ef27",
    "google-zapustila-zaschischyonnye-ii-servery-na-nvidia-blackwel-39004": "6ad9d8d691554b2467c39004",
    "perplexity-pridumala-kak-obuchat-ii-s-raskhodom-tokenov-v-13-r-fa581": "6ad9d2ed97126b54778fa581",
    "openai-vvodit-propusknoi-rezhim-dlya-agregatorov-791dc": "6ad9d0cef8edfc31bb5791dc",
    "deepseek-raskryla-kod-na-kotorom-rabotaet-eyo-ii-no-ne-vsyu-in-b5ec6": "6ad9cc85f8edfc31bb4b5ec6",
    "reklama-v-chatgpt-dobralas-do-89-stran-bolee-100-tysyach-rekla-fb1f5": "6ad9b67899791f7d2cbfb1f5",
    "tysyachi-ii-agentov-za-32-minuty-issledovali-milliony-kletok-m-938e7": "6ad9b315cba82619cbe938e7",
    "nvidia-opublikovala-arkhitekturu-s-apparatnym-stop-kranom-dlya-69bf0": "6ad9b0b5dda2334495a69bf0",
    "ii-pomog-naiti-dve-kriticheskie-dyry-v-php-pod-ugrozoi-okazali-b3016": "6ad9af1ae9368d4a2d1b3016",
    "claude-teper-pishet-pervym-anthropic-predstavila-proaktivnogo-d3e13": "6ad9aba3dda23344958d3e13",
    "volkswagen-podklyuchil-k-copilot-330-tysyach-sotrudnikov-ii-ag-97951": "6ad9a7a4e601f329d6997951",
    "google-budet-prodavat-modeli-openai-vmeste-so-svoimi-gemini-2b570": "6ad9a5ee95e73b66d202b570",
    "nvidia-vypustila-ii-dlya-poiska-v-tablitsakh-i-grafikakh-agent-77c3e": "6ad99ebe95e73b66d2f77c3e",
    "perplexity-perenesla-ii-agenta-na-mac-on-mozhet-rabotat-dazhe-bc45e": "6ad99b4108dabf01058bc45e",
    "243-milliona-chelovek-polzuyutsya-ii-v-yugo-vostochnoi-azii-te-548ea": "6ad87fc19f4a4f1f314548ea",
    "na-steam-next-fest-bolshe-8-tysyach-demoversii-odnu-razrabotch-0c86b": "6ad87ac2318e9e3914e0c86b",
    "v-derevya-vkruchivayut-datchiki-chtoby-ii-ponyal-kogda-im-nuzh-133e0": "6ad8776613ca4647d9d133e0",
    "ii-ostavili-bez-zadaniya-na-virtualnom-ostrove-on-postroil-khr-c0aae": "6ad854e8efbf813a134c0aae",
    "v-co-op-poyavilsya-ii-nadziratel-on-slushaet-razgovory-sotrudn-1b2bc": "6ad8520df441410ca8d1b2bc",
    "sony-khochet-pokazyvat-kadry-igr-eschyo-do-togo-kak-ikh-narisu-c5b1b": "6ad8477f46bcf26f508c5b1b",
}

class Batch5OriginalsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records=json.loads((ROOT/"news.json").read_text(encoding="utf-8"))
        cls.by_slug={r["id"]:r for r in cls.records}
        cls.catalog={r["dzen_id"]:r for r in json.loads(
            (ROOT/"data/editorial_full_catalog_snapshot.json").read_text(encoding="utf-8"))["entries"]}

    def test_exact_count_and_unique_source_ids(self):
        self.assertEqual(len(EXPECTED),30)
        self.assertGreaterEqual(len(self.records),131)
        self.assertEqual(len(self.records),len({r["url"] for r in self.records}))
        ids=[r["dzen_id"] for r in self.records if r.get("dzen_id")]
        self.assertEqual(len(ids),len(set(ids)))

    def test_original_title_date_cover_and_full_html(self):
        for slug, dzen_id in EXPECTED.items():
            with self.subTest(slug=slug):
                row=self.by_slug[slug]
                old=self.catalog[dzen_id]
                self.assertEqual(old["title_evidence"],"recorded")
                self.assertEqual(old["url_evidence"],"recorded_in_editorial_archive")
                self.assertEqual(row["dzen_id"],dzen_id)
                self.assertEqual(row["title"],old["title"])
                self.assertEqual(row["dzen_url"],old["dzen_url"])
                pub=dt.datetime.fromisoformat(old["published_at_utc"].replace("Z","+00:00"))
                self.assertEqual(row["published_at_utc"],pub.strftime("%Y-%m-%dT%H:%M:%SZ"))
                self.assertEqual(row["published"],pub.astimezone(ZoneInfo("Asia/Yekaterinburg")).date().isoformat())
                self.assertNotIn("modified_at_utc",row)
                artwork=ROOT/row["cover"]
                self.assertTrue(artwork.is_file(),row["cover"])
                self.assertGreater(artwork.stat().st_size,15000)
                self.assertEqual(artwork.read_bytes()[:4],b"RIFF")
                page=(ROOT/row["url"]/"index.html").read_text(encoding="utf-8")
                self.assertIn('rel="canonical" href="https://iipike.ru/'+row["url"]+'"',page)
                self.assertIn('article:published_time" content="'+row["published_at_utc"]+'"',page)
                self.assertIn('"datePublished": "'+row["published_at_utc"]+'"',page)
                self.assertNotIn('"dateModified":',page)
                self.assertIn(row["dzen_url"],page)
                body=page.split('<article class="article-text">',1)[-1].split("</article>",1)[0]
                self.assertGreater(len(html.unescape(re.sub("<[^>]*>"," ",body))),570)

    def test_sitemap_contains_each_exactly_once(self):
        sitemap=ET.parse(ROOT/"sitemap.xml").getroot()
        urls=[el.text for el in sitemap.iter() if el.tag.endswith("}loc")]
        self.assertEqual(len(urls),len(set(urls)))
        for slug in EXPECTED:
            self.assertEqual(urls.count("https://iipike.ru/"+self.by_slug[slug]["url"]),1)

if __name__=="__main__":
    unittest.main()
