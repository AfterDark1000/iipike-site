"""Regression coverage for Yandex.Metrika on existing and future HPII pages."""
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "assets" / "social-footer.js"
COUNTER = "114100188"


class ScriptSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.script_srcs = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            src = dict(attrs).get("src")
            if src:
                self.script_srcs.append(src)


class YandexMetrikaTests(unittest.TestCase):
    def test_single_counter_and_requested_options(self):
        script = SHARED.read_text(encoding="utf-8")
        self.assertEqual(script.count("https://mc.yandex.ru/metrika/tag.js?id=" + COUNTER), 1)
        self.assertEqual(len(re.findall(r"ym\(114100188, 'init'", script)), 1)
        for option in ("ssr: true", "webvisor: true", "clickmap: true",
                       'ecommerce: "dataLayer"', "referrer: document.referrer",
                       "url: location.href", "accurateTrackBounce: true",
                       "trackLinks: true"):
            self.assertIn(option, script)

    def test_all_public_html_pages_load_shared_tracker(self):
        # All first-party pages (including historical and future generated news
        # pages) use the shared footer JS. The Yandex verification HTML is not a page.
        pages = sorted(ROOT.rglob("index.html"))
        self.assertGreater(len(pages), 200)
        for page in pages:
            # Campaign shortcuts are redirect-only and must not load the tracker.
            # A tracker on these pages would count a duplicate pageview.
            if page in (ROOT / "dzen" / "index.html",
                        ROOT / "threads" / "index.html"):
                continue
            html = page.read_text(encoding="utf-8")
            if "<html" not in html.lower():
                continue
            parser = ScriptSources()
            parser.feed(html)
            matches = [x for x in parser.script_srcs if "social-footer.js" in x]
            self.assertEqual(len(matches), 1, str(page.relative_to(ROOT)))
            self.assertEqual((page.parent / matches[0]).resolve(), SHARED.resolve(),
                             str(page.relative_to(ROOT)))

    def test_future_generated_templates_reference_shared_file(self):
        for file in ("scripts/publish_approved_article.py", "scripts/site_topics.py",
                     "scripts/site_rubrics.py", "scripts/publish_draft_preview.py"):
            source = (ROOT / file).read_text(encoding="utf-8")
            self.assertIn("assets/social-footer.js", source, file)

    def test_tracker_code_is_valid_javascript(self):
        node = shutil.which("node")
        if node:
            checked = subprocess.run([node, "--check", str(SHARED)],
                                     capture_output=True, text=True, timeout=10)
            self.assertEqual(checked.returncode, 0, checked.stderr)


if __name__ == "__main__":
    unittest.main()
