"""Safety checks for the read-only editorial overview on GitHub Pages."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "admin" / "index.html"


class AdminOverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = ADMIN.read_text(encoding="utf-8")

    def test_dashboard_has_real_git_sources(self):
        self.assertIn("raw.githubusercontent.com/AfterDark1000/iipike-site/editorial-intake/editorial_inbox/", self.html)
        self.assertIn('QUEUE_STATUS.md', self.html)
        self.assertIn('DZEN_QUEUE.md', self.html)
        self.assertIn("Дзен пока не подтверждён", self.html)

    def test_read_only_and_not_indexed(self):
        self.assertIn('name="robots" content="noindex,nofollow,noarchive"', self.html)
        self.assertIn("GitHub Pages нет авторизации", self.html)
        self.assertNotIn("github_pat_", self.html)
        self.assertNotIn("api.github.com/repos/", self.html)
        self.assertNotIn('method="post"', self.html.lower())
        self.assertNotIn('method:"POST"', self.html)
        self.assertIn("localStorage.setItem(MARKS_KEY", self.html)
        self.assertIn("Отметки для Дзена сохраняются только в текущем браузере", self.html)
        self.assertIn("https://raw.githubusercontent.com/AfterDark1000/iipike-site/editorial-intake/", self.html)
        self.assertNotIn('url.replace(/^https:', self.html)

    def test_existing_release_files_untouched(self):
        self.assertTrue((ROOT / ".github/workflows/site-first-scheduled-release.yml").is_file())
        self.assertTrue((ROOT / ".github/workflows/dzen-reading-queue.yml").is_file())

    def test_dzen_mark_controls_and_live_catalog(self):
        for phrase in ("В отложенных", "Уже опубликована", "Вернуть в список",
                       "published_observed_in_feed", "reconcileDzenCatalog"):
            self.assertIn(phrase, self.html)

    def test_dzen_tools_present(self):
        for label in ("Копировать заголовок", "Копировать текст с оформлением", "Скачать выбранные обложки ZIP"):
            self.assertIn(label, self.html)


if __name__ == "__main__":
    unittest.main()
