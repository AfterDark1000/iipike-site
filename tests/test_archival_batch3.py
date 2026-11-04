"""Third HPII archival batch: source-preserving HTML, dates, cover and links."""
import datetime as dt
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "microsoft-offers-60k-exits": "6ae0813b6c54fa23921064ed",
    "openai-power-grid-georgia-1000mw": "6ae96ea055a910701b153d93",
    "openai-gpt6-astra-household-benchmark": "6ae96c5329933216f113c227",
    "openai-abu-dhabi-regulation-ai": "6ae9687670b2207347df850c",
    "telus-ai-calls-cancellations": "6ae80f62121f043a98f7369e",
    "chainalysis-hacked": "6ae70acf4d27f64e5d8cfa61",
    "malware-ai-scores-victims": "6ae70789fc598f0048316738",
    "claude-mouse-brain-injection": "6ae6fee08b88aa0944ccbca9",
    "openai-gpt6-biologists-restricted": "6ae5a75be0d1375c19deb74b",
    "ai-680-tokens-second": "6ae5a5b3121f043a98a6aa6d",
    "claude-code-pentagon-systems": "6ae4bb48a578bc23f57e4ef7",
    "pika-15s-video-7s-compute": "6ae4b9d4ffd69737bf8f44e2",
    "elevenlabs-sfxv3-ai-sound-design": "6ae41b330c75c303c14a0b24",
    "nvidia-ai-meeting-secretary": "6ae4198f4e1c1848278239fd",
    "indian-voice-model-elevenlabs": "6ae4129ae0d1375c19009615",
    "runway-ai-advertising-agent": "6ae4103afc598f004841c92e",
    "nate-soares-retirement-apocalypse": "6ae32079e82b1b48f8507713",
    "chatgpt-service-now-support": "6ae31c844e1c18482737021c",
    "microsoft-copilot-twenty-models": "6ae2e08fd2f43220dc0c3284",
    "rime-prism-voice-guardrails": "6ae2dbbda9ed44022355977d",
    "microsoft-mai-image-editor": "6ae2d8b70c75c303c16b4450",
    "gemini4-carbon-ranking": "6ae2c0cf4d27f64e5d7851ae",
    "kling40-api-video-price": "6ae1d1965527bd132901fca2",
    "runway-app-studio-no-code-video": "6ae1cde70c75c303c1f0a39a",
    "south-korea-ai-data-theft": "6ae19b93d73786100d0ca5e9",
    "oracle-chatgpt-accounting": "6ae1952e8b88aa0944685b2b",
    "claude-35k-antibodies": "6ae194224d27f64e5daa7c7b",
    "apple-iwork-ai-agents": "6ae19154d2f43220dc1a7aa6",
    "google-genie4-worlds": "6ae18fd1d73786100df5c71d",
    "netherlands-civil-service-ai-cuts": "6ae0ac67fdcd464d1ef2db72"
}
BASE = "https://iipike.ru"

class ThirdBatchIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.news = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
        cls.by_slug = {x["id"]: x for x in cls.news}
        cls.catalog = {x["dzen_id"]: x for x in
                       json.loads((ROOT / "data/editorial_full_catalog_snapshot.json").read_text(encoding="utf-8"))["entries"]}

    def test_all_30_new_articles_are_unique_and_originally_dated(self):
        self.assertGreaterEqual(len(self.news), 71)
        self.assertEqual(len(set(x["url"] for x in self.news)), len(self.news))
        self.assertEqual(len(set(x["dzen_id"] for x in self.news if x.get("dzen_id"))),
                         len([x for x in self.news if x.get("dzen_id")]))
        for slug, dzen_id in EXPECTED.items():
            with self.subTest(slug=slug):
                row = self.by_slug[slug]
                original = self.catalog[dzen_id]
                self.assertEqual(row["dzen_id"], dzen_id)
                self.assertEqual(row["title"], original["title"])
                self.assertEqual(row["dzen_url"], original["dzen_url"])
                self.assertEqual(original["title_evidence"], "recorded")
                self.assertEqual(original["url_evidence"], "recorded_in_editorial_archive")
                imported = dt.datetime.fromisoformat(row["published_at_utc"].replace("Z","+00:00"))
                published = dt.datetime.fromisoformat(original["published_at_utc"].replace("Z","+00:00"))
                self.assertEqual(imported, published)
                self.assertEqual(row["published"], published.astimezone(ZoneInfo("Asia/Yekaterinburg")).date().isoformat())
                self.assertNotIn("modified_at_utc", row, "Do not invent substantive updates")

    def test_each_original_is_a_real_standalone_site_page_with_own_cover(self):
        for slug in EXPECTED:
            row = self.by_slug[slug]
            image = ROOT / row["cover"]
            self.assertTrue(image.exists(), image)
            self.assertGreater(image.stat().st_size, 15_000)
            self.assertEqual(image.read_bytes()[:4], b"RIFF", image)
            page = (ROOT / row["url"] / "index.html").read_text(encoding="utf-8")
            self.assertIn(f'rel="canonical" href="{BASE}/{row["url"]}"', page)
            self.assertIn('article:published_time" content="' + row["published_at_utc"] + '"',page)
            self.assertIn('"datePublished": "' + row["published_at_utc"] + '"', page)
            self.assertIn(row["dzen_url"], page)
            self.assertIn(row["cover"], page)
            self.assertNotIn("На сайте:", page)
            self.assertNotIn("Первоначально опубликовано в Дзене:", page)
            self.assertNotIn('"dateModified":', page)
            body = page.split('<article class="article-text">',1)[-1].split('</article>',1)[0]
            self.assertGreater(len(re.sub("<[^>]+>", "", body)), 600, slug)

    def test_sitemap_lists_all_new_articles_once(self):
        root = ET.parse(ROOT / "sitemap.xml").getroot()
        urls = [x.text for x in root.iter() if x.tag.endswith("}loc")]
        self.assertEqual(len(urls),len(set(urls)))
        for slug in EXPECTED:
            self.assertEqual(urls.count(BASE + "/" + self.by_slug[slug]["url"]),1)

if __name__ == "__main__":
    unittest.main()
