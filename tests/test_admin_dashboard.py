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
        self.assertIn("HPII — editorial text + cover inbox (VALIDATION + SAFE QUOTE FIX)", dzen)
        self.assertIn("HPII — approved autonomous story/cover to editorial queue (NO DIRECT PUBLICATION)", dzen)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", dzen)
        self.assertIn("async function generateFromFreshHead()", dzen)
        self.assertIn("await generateFromFreshHead()", dzen)
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
                      "Скачать выбранные обложки ZIP"):
            self.assertIn(label, self.html)
        for removed_id in ('id="copySelected"', 'id="copyPlain"'):
            self.assertNotIn(removed_id, self.html)

    def test_dzen_inline_illustrations_are_separate_from_cover(self):
        for phrase in ("Иллюстрации ↓", "ДОПОЛНИТЕЛЬНЫЕ ИЛЛЮСТРАЦИИ · БЕЗ ОБЛОЖКИ",
                       "Скачать все иллюстрации ZIP", ".article-text img[src]",
                       "/assets/editorial/inline/", "downloadIllustrationsZip",
                       "sitePublished:num===1||num===3",
                       "Обложка в этот список не входит"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.html)
        self.assertIn("if(o.sitePublished)", self.html)
        self.assertIn("main/articles/", self.html)
        self.assertIn("Опубликованная HTML-страница статьи пока не найдена", self.html)

    def test_dzen_controls_are_grouped_and_illustration_gallery_is_compact(self):
        for phrase in ('" item-dzen"', '"action-status"', '"action-primary"',
                       '"action-assets"', '"action-link"', 'Текст для Дзена',
                       'repeat(5,minmax(0,1fr))', 'height:104px',
                       'padding:12px 16px', 'max-width:min(1160px,96vw)',
                       '@media(max-width:900px)', '@media(max-width:560px)'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.html)
        self.assertIn('el("button","small primary","Текст для Дзена")', self.html)
        self.assertIn('background:#f1f7f5', self.html)
        self.assertIn('border-right:1px solid var(--line)', self.html)

    def test_mobile_rich_copy_has_honest_fallback_and_accessible_feedback(self):


        for phrase in ('id="copyFeedback"',
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
