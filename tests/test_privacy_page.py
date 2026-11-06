"""Read-only structural tests for the published privacy and analytics controls."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PrivacyPageTests(unittest.TestCase):
    def test_privacy_page_is_readable_and_accessible_from_all_footers(self):
        page = (ROOT / "privacy/index.html").read_text(encoding="utf-8")
        footer = (ROOT / "assets/social-footer.js").read_text(encoding="utf-8")
        self.assertIn("<h1>Конфиденциальность и аналитика</h1>", page)
        self.assertIn("Яндекс Метрику", page)
        self.assertIn("Вебвизор", page)
        self.assertIn("GitHub Pages", page)
        self.assertIn("Отказ не мешает читать статьи", page)
        self.assertIn("Настройки аналитики", page)
        self.assertIn('policy.href = "https://iipike.ru/privacy/"', footer)
        self.assertIn('settings.type = "button"', footer)
        self.assertIn('src="../assets/social-footer.js"', page)
        self.assertIn('class="footer"', page)

    def test_no_automatic_analytics_on_redirects_or_privacy_legal_text(self):
        text = (ROOT / "privacy/index.html").read_text(encoding="utf-8")
        self.assertNotIn("mc.yandex.ru", text)
        self.assertNotIn("<script>ym(", text)
        self.assertNotIn("<script src=\"https://mc.yandex.ru", text)
        self.assertNotIn("<loc>https://iipike.ru/privacy/</loc>",
                         (ROOT / "sitemap.xml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
