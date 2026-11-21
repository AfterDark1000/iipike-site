"""Offline regression tests for an INERT VK RSS experiment; never posts to VK."""
import unittest
import xml.etree.ElementTree as ET

from scripts import vk_rss_experiment as lab

class VKLabSafety(unittest.TestCase):
    def test_frozen_variants_match_generator(self):
        baseline = (lab.DEST / "01-control.xml").read_text(encoding="utf-8")
        generated = lab.render(baseline)
        self.assertEqual(len(generated), 4)
        for name, xml in generated.items():
            self.assertEqual((lab.DEST / name).read_text(encoding="utf-8"), xml)

    def test_same_article_guid_date_and_image_all_variants(self):
        variants = sorted(lab.DEST.glob("*.xml"))
        self.assertEqual(len(variants), 4)
        guids, dates, images = set(), set(), set()
        for path in variants:
            channel = ET.parse(path).getroot().find("channel")
            items = channel.findall("item")
            self.assertEqual(len(items), 1, path.name)
            item = items[0]
            guids.add(item.findtext("guid"))
            dates.add(item.findtext("pubDate"))
            enclosure = item.find("enclosure")
            self.assertEqual(enclosure.attrib["type"], "image/jpeg")
            images.add(enclosure.attrib["url"])
            self.assertIn(enclosure.attrib["url"], item.findtext("description"))
            self.assertNotIn("typefully", str(path).lower())
        self.assertEqual(guids, {lab.ART_URL})
        self.assertEqual(dates, {"Sat, 21 Nov 2026 17:45:41 GMT"})
        self.assertEqual(images, {
            "https://iipike.ru/assets/vk/meta-muse-chrome-login-20261120.jpg"})

    def test_only_hypothesized_fields_differ(self):
        a = lab.DEST
        control = ET.parse(a / "01-control.xml").getroot().find("./channel/item")
        media = ET.parse(a / "02-media-image.xml").getroot().find("./channel/item")
        none = ET.parse(a / "03-photo-only-diagnostic.xml").getroot().find("./channel/item")
        text_link = ET.parse(a / "04-text-url-diagnostic.xml").getroot().find("./channel/item")
        self.assertEqual(media.findtext("link"), control.findtext("link"))
        self.assertIsNotNone(media.find("{http://search.yahoo.com/mrss/}content"))
        self.assertIsNotNone(media.find("{http://search.yahoo.com/mrss/}thumbnail"))
        self.assertIsNone(none.find("link"))
        self.assertIsNone(text_link.find("link"))
        self.assertNotIn(lab.ART_URL, none.findtext("description"))
        self.assertIn(lab.ART_URL, text_link.findtext("description"))
        self.assertEqual(control.findtext("description"), media.findtext("description"))

if __name__ == "__main__":
    unittest.main()
