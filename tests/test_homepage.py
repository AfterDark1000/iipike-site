"""Offline homepage regression tests: V1 navigation, live published cards and compact footer."""
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "index.html"
CSS = ROOT / "assets" / "site.css"

class Tags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.ids = []
        self.links = []
        self.headings = []
        self.stack = []
        self.errors = []
    def handle_starttag(self, tag, attrs):
        p = dict(attrs)
        self.tags.append(tag)
        if "id" in p:
            self.ids.append(p["id"])
        if tag == "a":
            if "a" in self.stack:
                self.errors.append("nested interactive anchors")
            self.links.append(p.get("href"))
        if tag == "img" and not p.get("alt"):
            self.errors.append("image missing accessible alt")
        if tag in ("h1", "h2", "h3"):
            self.headings.append(tag)
        if tag not in ("meta", "link", "img", "br", "hr", "input", "source"):
            self.stack.append(tag)
    def handle_endtag(self, tag):
        if tag in self.stack:
            i = len(self.stack) - 1 - self.stack[::-1].index(tag)
            self.stack = self.stack[:i]


class HomepageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML.read_text(encoding="utf-8")
        cls.css = CSS.read_text(encoding="utf-8")
        cls.parsed = Tags()
        cls.parsed.feed(cls.html)

    def test_page_has_accessible_navigation_and_distinct_sections(self):
        self.assertFalse(self.parsed.errors)
        self.assertEqual(self.parsed.headings.count("h1"), 1)
        self.assertEqual(len(self.parsed.ids), len(set(self.parsed.ids)))
        for key in ("content", "archive", "short-news", "dossier", "focus"):
            self.assertIn(key, self.parsed.ids)
        for link in ("registry/", "drafts/", "articles/", "feed.xml", "entities/", "briefs/", "dossier/"):
            self.assertIn(link, self.parsed.links)
        self.assertIn("Свежие публикации", self.html)
        self.assertIn("HPII_PUBLISHED_SECTION_START", self.html)
        self.assertIn("home-site-posts", self.html)
        self.assertNotIn("https://dzen.ru/iipike", self.html)

    def test_homepage_first_party_articles_are_current_and_readable(self):
        import json
        from scripts.site_home import update_home, sorted_published
        from scripts.site_rubrics import publication_date
        records = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
        self.assertEqual(update_home(self.html, records), self.html)
        newest = sorted_published(records)[0]
        self.assertIn('href="' + newest["url"] + '"', self.html)
        self.assertIn('src="' + newest["cover"] + '"', self.html)
        # The newest story can be pinned (sentence-case date) or on the main news card (uppercase date).
        visible_date = publication_date(newest["published"])
        self.assertTrue(visible_date in self.html or visible_date.upper() in self.html)
        self.assertNotIn("ПИЛОТНЫЙ ВЫПУСК", self.html)
        self.assertNotIn("Полная новостная лента ХПИИ сейчас выходит в Дзене", self.html)
        for item in sorted_published(records)[:5]:
            self.assertIn('href="' + item["url"] + '"', self.html)

    def test_v1_menu_and_no_legacy_sections(self):
        menu = re.search(r'<nav class="menu home-menu"[^>]*>(.*?)</nav>', self.html, re.S).group(1)
        self.assertEqual(re.findall(r'href="([^"]+)"', menu),
                         ["articles/", "briefs/", "dossier/", "entities/"])
        for removed in ("home-workshop", "home-latest", "home-endnote",
                        "home-draft-live", "home-dzen-list", "latestPublished", "newestDraft"):
            self.assertNotIn(removed, self.html)
        self.assertIn('src="assets/social-footer.js"', self.html)
        self.assertEqual(self.html.count('assets/social-footer.js'), 1)
        self.assertIn('a, a:hover, a:focus, a:visited, a:active{text-decoration:none!important}', self.css)

    def test_homepage_css_only_adds_scoped_rules(self):
        self.assertIn("/* Homepage / editorial front page.", self.css)
        self.assertIn(".home-news-grid", self.css)
        self.assertIn(".home-feature-link", self.css)
        self.assertIn("@media (max-width:480px)", self.css)
        self.assertIn("prefers-reduced-motion", self.css)
        self.assertIn("assets/site.css", self.html)

    def test_feature_cover_uses_natural_16_by_9_layout_not_black_bands(self):
        self.assertIn('class="home-feature-image">', self.html)
        self.assertNotIn('--feature-art:', self.html)
        self.assertNotIn('background-image:var(--feature-art)', self.css)
        self.assertNotIn('min-height:390px', self.css)
        image_rule = self.css.split('.home-feature-image img{', 1)[1].split('}', 1)[0]
        self.assertIn('aspect-ratio:16/9', image_rule)
        self.assertIn('object-fit:contain', image_rule)
        self.assertIn('height:auto', image_rule)

    def test_small_home_cards_show_headline_before_date_and_rubric(self):
        import re
        cards = re.findall(r'<a class="home-site-post".*?</a>', self.html)
        self.assertEqual(len(cards), 4)
        for card in cards:
            self.assertLess(card.index('<h3>'), card.index('<small class="date">'))
            self.assertLess(card.index('<small class="date">'),
                            card.index('class="home-site-read"'))

    def test_local_paths_resolve(self):
        for path in ("assets/site.css", "assets/icon.svg",
                     "assets/google-search-links.svg",
                     "articles/google-search-ai-links/index.html",
                     "drafts/index.json", "registry/index.html", "feed.xml"):
            self.assertTrue((ROOT / path).is_file(), path)

    def test_no_obsolete_inline_scripts(self):
        self.assertEqual(re.findall(r"<script>(.*?)</script>", self.html, flags=re.S), [])

if __name__ == "__main__":
    unittest.main()
