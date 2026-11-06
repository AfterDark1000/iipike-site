"""Offline tests for the X short attribution landing page."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.metas = []
        self.links = []
        self.anchors = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            self.metas.append(attrs)
        elif tag == "link":
            self.links.append(attrs)
        elif tag == "a":
            self.anchors.append(attrs)


class XRedirectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "x" / "index.html").read_text(encoding="utf-8")
        cls.tags = Elements()
        cls.tags.feed(cls.page)

    def test_clean_short_route_redirects_to_home_with_x_source(self):
        meta = next(m for m in self.tags.metas if m.get("http-equiv") == "refresh")
        self.assertIn("url=", meta["content"])
        destination = meta["content"].split("url=", 1)[1]
        url = urlsplit(destination)
        self.assertEqual((url.scheme, url.netloc, url.path), ("https", "iipike.ru", "/"))
        self.assertEqual(parse_qs(url.query), {
            "utm_source": ["x"],
            "utm_medium": ["social"],
            "utm_campaign": ["hpii_profile"],
        })

    def test_browser_history_and_manual_fallback_match(self):
        fallback = self.tags.anchors[0]["href"]
        self.assertIn('window.location.replace("' + fallback + '")', self.page)
        self.assertIn("utm_source=x", fallback)

    def test_not_indexed_as_duplicate_and_not_double_tracked(self):
        self.assertTrue(any(m.get("name") == "robots"
                            and m.get("content") == "noindex, follow"
                            for m in self.tags.metas))
        self.assertTrue(any(l.get("rel") == "canonical"
                            and l.get("href") == "https://iipike.ru/"
                            for l in self.tags.links))
        self.assertNotIn("social-footer.js", self.page)
        self.assertNotIn("mc.yandex.ru", self.page)
        self.assertNotIn("114100188", self.page)

    def test_redirect_route_never_enters_sitemap(self):
        sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
        self.assertNotIn("<loc>https://iipike.ru/x/</loc>", sitemap)


if __name__ == "__main__":
    unittest.main()
