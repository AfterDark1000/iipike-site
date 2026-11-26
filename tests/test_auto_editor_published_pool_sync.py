"""Reconcile only proven published autonomous full articles into their raw pool."""
import copy
import hashlib
import json
from unittest.mock import patch
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

    def source_upgrade_fixture(self):
        request = "pilot-20261119-001.json"
        request_bytes = b'{"action":"claim_ordinary"}'
        primary = "https://primary.example.org/announcement"
        public = dict(self.article, source_url=primary, title="Verified primary source article")
        content = {"title": public["title"], "article_markdown": "Human-reviewed article.", "source_url": primary}
        receipt = {"request": request, "status": "reserved", "worker": "hpii-auto-editor",
                   "article_id": ID, "pool_id": POOL_ID, "pool_sequence": 44, "source_url": SOURCE,
                   "claimed_at": self.item["review_started_at"], "request_sha256": hashlib.sha256(request_bytes).hexdigest()}
        for sub, data in [("data/auto_editor/requests/" + request, request_bytes),
                          ("data/auto_editor/receipts/" + request, json.dumps(receipt).encode()),
                          ("content/approved/" + ID + ".json", json.dumps(dict(content, slug=ID, status="approved", published_at_utc=STAMP)).encode())]:
            path = self.root / sub
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        draft_sha, decision_sha, cover_sha = "a"*40, "b"*40, "c"*40
        stamp = self.item["review_started_at"]
        stem = ID + "-r1"
        records = {
            "editorial_inbox/auto_drafts/" + ID + ".json":
                (dict(article_id=ID, request=request, pool_id=POOL_ID, pool_sequence=44, status="ready_for_review",
                      revision=1, created_at=stamp, updated_at=stamp, content=content), draft_sha),
            "editorial_inbox/auto_decisions/" + stem + ".json":
                (dict(article_id=ID, revision=1, updated_at=stamp, draft_blob_sha=draft_sha, action="approve_text",
                      status="text_approved_cover_pending", channel="hpii-admin-oauth-gateway", decided_by="owner", decided_at=stamp), decision_sha),
            "editorial_inbox/stories/" + ID + ".json":
                (dict(content, id=ID, status="editor_approved", approved_by="human_editor"), "d"*40),
            "editorial_inbox/auto_handoffs/" + stem + "-v1.json":
                (dict(article_id=ID, text_revision=1, cover_version=1, status="handed_off_to_site_queue",
                      source_draft_blob_sha=draft_sha, text_decision_blob_sha=decision_sha, cover_decision_blob_sha=cover_sha,
                      cover_blob_sha="e"*40, story_path="editorial_inbox/stories/" + ID + ".json"), "f"*40),
            "editorial_inbox/auto_cover_decisions/" + stem + "-v1.json":
                (dict(article_id=ID, text_revision=1, cover_version=1, action="approve_cover",
                      status="cover_approved_handoff_pending", channel="hpii-admin-oauth-gateway", decided_by="owner",
                      source_draft_blob_sha=draft_sha, cover_blob_sha="e"*40, decided_at=stamp), cover_sha),
        }
        return public, records

    def test_human_approved_source_upgrade_preserves_original_claim(self):
        public, records = self.source_upgrade_fixture()
        with patch.object(sync, "intake_record", side_effect=lambda root, ref, path: records.get(path, (None, None))):
            final, changes = sync.reconcile(self.pool, [public], root=self.root, intake_ref="snapshot")
        self.assertEqual(len(changes), 1)
        row = final["items"][0]
        self.assertEqual(row["status"], "approved")
        self.assertEqual(row["source_url"], SOURCE)
        self.assertEqual(row["closed_at"], STAMP)
        self.assertIn(public["source_url"], row["note"])

    def test_changed_source_requires_every_bound_approval_and_receipt(self):
        public, records = self.source_upgrade_fixture()
        for path in records:
            with self.subTest(missing=path), patch.object(sync, "intake_record",
                    side_effect=lambda root, ref, name: (None, None) if name == path else records.get(name, (None, None))):
                with self.assertRaisesRegex(ValueError, "source differs"):
                    sync.reconcile(self.pool, [public], root=self.root, intake_ref="snapshot")
        for path, field, invalid in [
                ("editorial_inbox/auto_drafts/" + ID + ".json", "pool_id", "wrong"),
                ("editorial_inbox/auto_decisions/" + ID + "-r1.json", "draft_blob_sha", "wrong"),
                ("editorial_inbox/auto_cover_decisions/" + ID + "-r1-v1.json", "action", "revise_cover"),
                ("editorial_inbox/auto_handoffs/" + ID + "-r1-v1.json", "source_draft_blob_sha", "wrong")]:
            bad = copy.deepcopy(records)
            bad[path][0][field] = invalid
            with self.subTest(field=field), patch.object(sync, "intake_record",
                    side_effect=lambda root, ref, name: bad.get(name, (None, None))):
                with self.assertRaisesRegex(ValueError, "source differs"):
                    sync.reconcile(self.pool, [public], root=self.root, intake_ref="snapshot")
        receipt_path = self.root / "data/auto_editor/receipts/pilot-20261119-001.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["pool_sequence"] = 999
        receipt_path.write_text(json.dumps(receipt))
        with patch.object(sync, "intake_record", side_effect=lambda root, ref, path: records.get(path, (None, None))):
            with self.assertRaisesRegex(ValueError, "source differs"):
                sync.reconcile(self.pool, [public], root=self.root, intake_ref="snapshot")
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

    def test_unrelated_bad_approved_record_is_not_silently_accepted(self):
        # The reconciliation helper remains strict; workflow isolation should
        # stop an unrelated raw-data defect from disrupting site publication.
        unrelated = copy.deepcopy(self.item)
        unrelated.update(
            id="n-0000000000000002",
            sequence=45,
            title="Previously approved unrelated human story",
            status="approved",
            article_id="human-story",
            review_started_at=None,
            closed_at=None,
            note="Approved by a human, but missing historical closure metadata",
        )
        invalid = {"schema_version": 1, "note": "test",
                   "items": [self.item, unrelated]}
        with self.assertRaisesRegex(ValueError, "Closed item requires closed_at"):
            sync.reconcile(invalid, [self.article], root=self.root)

    def test_release_workflow_isolates_raw_pool_validation_failure(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/site-first-scheduled-release.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("if ! python3 scripts/site_news_pool.py --validate; then", workflow)
        self.assertIn("AUTO_EDITOR_POOL_SYNC_SKIPPED_INVALID_POOL", workflow)
        self.assertIn("exit 0\n            fi", workflow)
        self.assertIn("python3 scripts/sync_published_auto_editor_pool.py --write", workflow)

    def test_malformed_claim_without_exact_identity_is_never_closed(self):
        self.pool["items"][0]["note"] = "AUTO_EDITOR claim=unexpected no article id"
        same, updates = sync.reconcile(self.pool, [self.article], root=self.root)
        self.assertEqual(updates, [])
        self.assertEqual(same, self.pool)


if __name__ == "__main__":
    unittest.main()
