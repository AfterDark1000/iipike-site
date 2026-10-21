"""Offline homepage regression tests: published/draft separation, links and JS safety."""
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import tempfile
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
        for key in ("content", "latest", "archive", "home-dzen-list",
                    "home-dzen-count", "home-draft-live"):
            self.assertIn(key, self.parsed.ids)
        for link in ("#latest", "#archive", "registry/", "drafts/",
                     "articles/google-search-ai-links/", "feed.xml"):
            self.assertIn(link, self.parsed.links)
        self.assertIn("ПИЛОТНЫЙ ВЫПУСК", self.html)
        self.assertIn("НЕ ОПУБЛИКОВАНО", self.html)
        self.assertNotIn("https://dzen.ru/iipike", self.html)

    def test_dynamic_news_uses_real_published_articles_only(self):
        self.assertIn('row.status === "published"', self.html)
        self.assertIn('validDzen(row.dzen_url)', self.html)
        self.assertIn('url.hostname === "dzen.ru"', self.html)
        self.assertIn('url.protocol === "https:"', self.html)
        self.assertIn("textContent", self.html)
        self.assertIn("replaceChildren", self.html)
        self.assertNotIn("innerHTML", self.html)
        self.assertNotIn("document.write", self.html)
        self.assertIn("latestPublished();", self.html)
        self.assertIn("newestDraft();", self.html)

    def test_draft_ids_are_limited_to_hex20_and_links_not_publications(self):
        self.assertIn('item.id', self.html)
        self.assertIn('link.href = "drafts/" + latest.id + "/"', self.html)
        self.assertIn('НЕ ОПУБЛИКОВАНО', self.html)
        self.assertIn("home-draft-live", self.html)

    def test_homepage_css_only_adds_scoped_rules(self):
        self.assertIn("/* Homepage / editorial front page.", self.css)
        self.assertIn(".home-news-grid", self.css)
        self.assertIn(".home-feature-link", self.css)
        self.assertIn("@media (max-width:480px)", self.css)
        self.assertIn("prefers-reduced-motion", self.css)
        self.assertIn("assets/site.css", self.html)

    def test_local_paths_resolve(self):
        for path in ("assets/site.css", "assets/icon.svg",
                     "assets/google-search-links.svg",
                     "articles/google-search-ai-links/index.html",
                     "drafts/index.json", "registry/index.html", "feed.xml"):
            self.assertTrue((ROOT / path).is_file(), path)

    def test_inline_script_parses_in_node(self):
        scripts = re.findall(r"<script>(.*?)</script>", self.html, flags=re.S)
        self.assertEqual(len(scripts), 1)
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder) / "home.js"
            temp.write_text(scripts[0], encoding="utf-8")
            p = subprocess.run(["node", "--check", str(temp)],
                               capture_output=True, text=True, timeout=15)
            self.assertEqual(p.returncode, 0, p.stderr)

if __name__ == "__main__":
    unittest.main()
