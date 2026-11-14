"""Regression guard: long site-first headlines should not fill an entire screen."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "assets/site.css").read_text(encoding="utf-8")
ARTICLE = (ROOT / "articles/china-nvidia-overseas-gpu-rentals-20261112/index.html").read_text(encoding="utf-8")


def rule(selector):
    """Return the final flat declaration for this selector (outside or inside @media)."""
    hits = re.findall(re.escape(selector) + r"\s*\{([^{}]+)\}", CSS)
    if not hits:
        raise AssertionError("CSS rule missing: " + selector)
    return hits


class ArticleHeaderStyleTests(unittest.TestCase):
    def test_article_title_has_its_own_smaller_responsive_scale(self):
        decl = rule(".article-title h1")[0]
        self.assertIn("font-size:clamp(36px,4.1vw,54px)", decl)
        self.assertIn("text-wrap:balance", decl)
        self.assertIn("overflow-wrap:break-word", decl)
        self.assertIn("line-height:1.12", decl)
        # Homepage headlines remain independent.
        self.assertIn(".home-intro h1", CSS)
        self.assertNotIn("h1{font-size:clamp(36px,4.1vw,54px)", CSS)

    def test_mobile_stays_legible_and_cover_moves_up(self):
        self.assertIn("font-size:clamp(30px,8.8vw,36px)", rule(".article-title h1")[-1])
        self.assertIn("margin-top:24px", rule(".article-title+.cover")[0])
        self.assertIn("margin-top:18px", rule(".article-title+.cover")[-1])
        self.assertIn("max-width:760px", rule(".article-title>.summary")[0])

    def test_existing_articles_use_shared_css_and_semantic_header(self):
        self.assertIn('href="../../assets/site.css"', ARTICLE)
        self.assertIn('<div class="article-title">', ARTICLE)
        self.assertIn('<h1>Китайские ИИ-компании', ARTICLE)
        self.assertIn('<figure class="cover">', ARTICLE)
        self.assertIn('class="topic-links"', ARTICLE)


if __name__ == "__main__":
    unittest.main()
