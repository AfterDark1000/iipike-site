"""Static, offline checks for shared HPII social footer; no network calls."""
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "assets" / "social-footer.js"
CSS = ROOT / "assets" / "site.css"


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.footers = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.scripts.append(values["src"])
        if tag == "footer" and "footer" in values.get("class", "").split():
            self.footers += 1


class SocialFooterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")
        cls.css = CSS.read_text(encoding="utf-8")

    def test_only_confirmed_platform_urls_are_clickable(self):
        expected = [
            "https://dzen.ru/iipike",
            "https://t.me/iipike",
            "https://vk.com/club242308928",
            "https://www.threads.com/@iipike.ai",
            "https://x.com/iipike_ai",
            "https://max.ru/channel_iipike",
            "https://www.youtube.com/channel/UCCEtLy-Id7ynkGtI_M-OtUQ",
            "https://www.instagram.com/iipike.ai/",
        ]
        for address in expected:
            self.assertIn('url: "' + address + '"', self.source)
        self.assertEqual(len(re.findall(r'url: "https://', self.source)), 8)
        self.assertNotRegex(self.source, r'url: "https://rutube\\.')
        self.assertIn("RuTube — видеоархив", self.source)
        self.assertIn("paused: true", self.source)

    def test_accessible_secure_links_and_no_external_dependencies(self):
        for text in ('a.target = "_blank"', 'a.rel = "noopener noreferrer"',
                     'aria-label', 'document.createElementNS',
                     'footer.footer', 'if (footer.querySelector(".hpi-social-section"))'):
            self.assertIn(text, self.source)
        self.assertNotIn("innerHTML", self.source)
        self.assertNotIn("fetch(", self.source)
        self.assertNotIn("document.write", self.source)
        self.assertIn("prefers-reduced-motion:reduce", self.css)
        self.assertIn(".hpi-social-grid", self.css)
        self.assertIn("grid-template-columns:repeat(2", self.css)
        node = shutil.which("node")
        if node:
            result = subprocess.run([node, "--check", str(SCRIPT)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_every_existing_page_has_working_relative_script(self):
        htmls = [
            ROOT / "index.html",
            ROOT / "registry/index.html",
            ROOT / "drafts/index.html",
            ROOT / "articles/google-search-ai-links/index.html",
        ] + sorted((ROOT / "drafts").glob("*/index.html"))
        self.assertGreaterEqual(len(htmls), 10)
        for path in htmls:
            parser = Scripts()
            parser.feed(path.read_text(encoding="utf-8"))
            self.assertEqual(parser.footers, 1, str(path))
            self.assertEqual(sum("social-footer.js" in x for x in parser.scripts), 1, str(path))
            src = next(x for x in parser.scripts if "social-footer.js" in x)
            self.assertTrue((path.parent / src).resolve() == SCRIPT.resolve(), str(path))
            self.assertEqual((path.parent / src).is_file(), True, str(path))

    def test_generated_drafts_keep_the_same_footer(self):
        template = (ROOT / "scripts" / "publish_draft_preview.py").read_text(encoding="utf-8")
        self.assertIn('src="{prefix}assets/social-footer.js"', template)


if __name__ == "__main__":
    unittest.main()
