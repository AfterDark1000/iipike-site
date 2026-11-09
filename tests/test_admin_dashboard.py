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
        self.assertIn("Публикация Дзена не подтверждена", self.html)

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

    def test_approved_editorial_updates_trigger_dzen_queue_even_without_workflow_on_intake_branch(self):
        dzen = (ROOT / ".github/workflows/dzen-reading-queue.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_run:", dzen)
        self.assertIn("HPII — editorial text + cover inbox (VALIDATION ONLY)", dzen)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", dzen)
        self.assertIn("github.event.workflow_run.head_branch == 'editorial-intake'", dzen)
        self.assertIn("branches: [main]", dzen)
        self.assertNotIn("branches: [main, editorial-intake]", dzen)
        self.assertIn("workflow_dispatch:", dzen)

    def test_site_publication_dispatches_dzen_queue_only_after_confirmed_release(self):
        release = (ROOT / ".github/workflows/site-first-scheduled-release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("actions: write", release)
        self.assertIn("id: release", release)
        self.assertIn("set -o pipefail", release)
        self.assertIn("ONE_RELEASE_REQUESTED:", release)
        self.assertIn("steps.release.outputs.published == 'true'", release)
        self.assertIn("steps.release.outcome == 'success'", release)
        self.assertIn("github.rest.actions.createWorkflowDispatch", release)
        self.assertIn("workflow_id: 'dzen-reading-queue.yml'", release)

    def test_dzen_tools_present(self):
        for label in ("Копировать заголовок", "Копировать текст с оформлением",
                      "Копировать выделением", "Только текст",
                      "Скачать выбранные обложки ZIP"):
            self.assertIn(label, self.html)

    def test_mobile_rich_copy_has_honest_fallback_and_accessible_feedback(self):
        for phrase in ('id="copySelected"', 'id="copyPlain"', 'id="copyFeedback"',
                       'role="status"', 'aria-live="polite"',
                       'function copyFormattedSelection()', 'document.execCommand("copy")',
                       '"text/html":new Blob([activeStory.html]',
                       '"text/plain":new Blob([plain]',
                       'function plainPreview()', 'var method=await copyArticleRich()',
                       'Скопирован только обычный текст',
                       'Сохранит ли Дзен оформление'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.html)
        self.assertNotIn('await copy(activeStory.markdown,activeStory.html)', self.html)
        self.assertNotIn('await navigator.clipboard.writeText(text)}', self.html)


if __name__ == "__main__":
    unittest.main()
