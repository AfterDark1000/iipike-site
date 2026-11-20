"""Reconcile only proven published autonomous full articles into their raw pool."""
import copy
from pathlib import Path
import tempfile
import unittest

from scripts import site_news_pool, sync_published_auto_editor_pool as sync

STAMP = "2026-11-20T00:07:22Z"
ID = "test-auto-editor-story-1"
POOL_ID = "n-0000000000000001"
SOURCE = "https://example.org/study/1/"


class AutoEditorPublishedSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.page = self.root / "articles" / ID / "index.html"
        self.page.parent.mkdir(parents=True)
        self.page.write_text("<html>Published article</html>", encoding="utf-8")
        self.item = {
            "id": POOL_ID, "sequence": 44, "title": "Full test article: confirmed published",
            "source_url": SOURCE, "summary": "Original story", "origin": "test",
            "priority": "normal", "status": "in_review",
            "added_at": "2026-11-18T00:00:00Z",
            "review_started_at": "2026-11-19T00:00:00Z",
            "closed_at": None, "article_id": None,
            "note": "AUTO_EDITOR claim=pilot-20261119-001.json; article_id=" + ID,
        }
        self.pool = {"schema_version": 1, "note": "isolated test", "items": [self.item]}
        self.article = {
            "id": ID, "url": "articles/" + ID + "/",
            "source_url": SOURCE.rstrip("/"), "published_at_utc": STAMP,
        }

    def test_close_real_published_once_preserve_exact_time_and_link(self):
        original = copy.deepcopy(self.pool)
        final, updates = sync.reconcile(self.pool, [self.article], root=self.root)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["sequence"], 44)
        self.assertEqual(final["items"][0]["status"], "approved")
        self.assertEqual(final["items"][0]["article_id"], ID)
        self.assertEqual(final["items"][0]["closed_at"], STAMP)
        self.assertIn("https://iipike.ru/articles/" + ID + "/", final["items"][0]["note"])
        self.assertEqual(self.pool, original)
        self.assertIs(site_news_pool.validate(final), final)
        same, updates_again = sync.reconcile(final, [self.article], root=self.root)
        self.assertEqual(updates_again, [])
        self.assertEqual(same, final)

    def test_in_review_stays_open_until_both_news_record_and_html_exist(self):
        result, updates = sync.reconcile(self.pool, [], root=self.root)
        self.assertEqual(updates, [])
        self.assertEqual(result["items"][0]["status"], "in_review")
        self.page.unlink()
        # A catalog row with no actual site page is corrupt publication state.
        # Fail closed rather than marking the original news as completed.
        with self.assertRaisesRegex(ValueError, "absent from actual site"):
            sync.reconcile(self.pool, [self.article], root=self.root)
        self.assertEqual(self.pool["items"][0]["status"], "in_review")

    def test_unrelated_reserved_story_never_reassigned(self):
        self.pool["items"][0]["note"] = "SHORT_EDITOR claim=short; pool_id=" + POOL_ID
        result, changed = sync.reconcile(self.pool, [self.article], root=self.root)
        self.assertEqual(changed, [])
        self.assertEqual(result, self.pool)

    def test_wrong_published_source_is_rejected_without_changes(self):
        bad = dict(self.article, source_url="https://another.example.org/another-study/")
        with self.assertRaisesRegex(ValueError, "source differs"):
            sync.reconcile(self.pool, [bad], root=self.root)
        self.assertEqual(self.pool["items"][0]["status"], "in_review")

    def test_wrong_url_or_missing_publication_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unexpected path"):
            sync.reconcile(self.pool, [dict(self.article, url="articles/someone-else/")],
                           root=self.root)
        with self.assertRaisesRegex(ValueError, "real timestamp"):
            sync.reconcile(self.pool, [dict(self.article, published_at_utc=None)],
                           root=self.root)

    def test_duplicate_claim_and_duplicate_publication_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate published article ID"):
            sync.reconcile(self.pool, [self.article, self.article], root=self.root)
        second = copy.deepcopy(self.item)
        second["id"] = "n-0000000000000002"
        second["sequence"] = 45
        second["title"] = "Another different claim with same article ID"
        pool = {"schema_version": 1, "note": "test", "items": [self.item, second]}
        with self.assertRaisesRegex(ValueError, "Multiple pool claims"):
            sync.reconcile(pool, [self.article], root=self.root)

    def test_malformed_claim_without_exact_identity_is_never_closed(self):
        self.pool["items"][0]["note"] = "AUTO_EDITOR claim=unexpected no article id"
        same, updates = sync.reconcile(self.pool, [self.article], root=self.root)
        self.assertEqual(updates, [])
        self.assertEqual(same, self.pool)


if __name__ == "__main__":
    unittest.main()
