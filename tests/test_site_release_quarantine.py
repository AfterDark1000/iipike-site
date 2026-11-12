"""A faulty approved story is isolated; the next can still publish."""
import datetime as dt
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.site_publication_queue import select_publishable_item
from scripts import site_release_quarantine as q

NOW = dt.datetime(2026, 11, 12, 8, 0, tzinfo=dt.timezone.utc)


def item(name):
    return {"id": name, "ready_at": NOW - dt.timedelta(hours=1),
            "not_before": None,
            "cover": "editorial_inbox/covers/" + name + ".webp"}


class QuarantineTests(unittest.TestCase):
    @patch("scripts.site_publication_queue.latest_site_first_publication",
           return_value=None)
    def test_bad_first_article_marked_and_next_is_selected_same_run(self, unused):
        items = [item("bad"), item("good")]
        with patch.object(q, "existing_error", return_value=None), \
             patch.object(q, "preflight_article",
                   side_effect=[ValueError("Broken editorial metadata"), True]) as check, \
             patch.object(q, "record_article_error") as record:
            selected = select_publishable_item(items, [], NOW, source_ref="editorial-sha")
        self.assertEqual(selected["id"], "good")
        self.assertEqual(check.call_count, 2)
        self.assertEqual(record.call_count, 1)
        self.assertEqual(record.call_args.args[1]["id"], "bad")

    @patch("scripts.site_publication_queue.latest_site_first_publication",
           return_value=None)
    def test_previous_marker_skips_article_without_retrying_it(self, unused):
        with patch.object(q, "existing_error",
                          side_effect=[{"reason": "Invalid cover"}, None]), \
             patch.object(q, "preflight_article", return_value=True) as check:
            selected = select_publishable_item(
                [item("bad"), item("good")], [], NOW, source_ref="sha")
        self.assertEqual(selected["id"], "good")
        check.assert_called_once()

    @patch("scripts.site_publication_queue.latest_site_first_publication",
           return_value=None)
    def test_infrastructure_error_must_fail_closed_not_quarantine_story(self, unused):
        with patch.object(q, "existing_error", return_value=None), \
             patch.object(q, "preflight_article", side_effect=OSError("git unavailable")), \
             patch.object(q, "record_article_error") as record:
            with self.assertRaisesRegex(OSError, "git unavailable"):
                select_publishable_item(
                    [item("bad"), item("good")], [], NOW, source_ref="sha")
        record.assert_not_called()

    @patch("scripts.site_publication_queue.latest_site_first_publication",
           return_value=None)
    def test_marker_write_failure_prevents_silent_skip(self, unused):
        with patch.object(q, "existing_error", return_value=None), \
             patch.object(q, "preflight_article", side_effect=ValueError("Invalid cover")), \
             patch.object(q, "record_article_error",
                          side_effect=OSError("Cannot persist marker")):
            with self.assertRaisesRegex(OSError, "Cannot persist marker"):
                select_publishable_item(
                    [item("bad"), item("good")], [], NOW, source_ref="sha")

    @patch("scripts.site_publication_queue.latest_site_first_publication",
           return_value=None)
    def test_explicit_target_never_publishes_an_unrequested_next_article(self, unused):
        with patch.object(q, "existing_error", return_value=None), \
             patch.object(q, "preflight_article", side_effect=ValueError("Bad cover")), \
             patch.object(q, "record_article_error"):
            with self.assertRaisesRegex(ValueError, "Requested article is blocked"):
                select_publishable_item(
                    [item("bad"), item("good")], [], NOW, source_ref="sha",
                    target="bad")

    def test_persisted_marker_is_only_valid_for_same_article_version(self):
        record = {"id": "bad", "status": "blocked_article_validation",
                  "reason": "Broken article", "fingerprint": "version-1"}
        with patch.object(q, "exists_at", return_value=True), \
             patch.object(q, "safe_git_blob_at", return_value=json.dumps(record)), \
             patch.object(q, "content_fingerprint", return_value="version-1"):
            self.assertEqual(q.existing_error("sha", item("bad"))["reason"],
                             "Broken article")
        with patch.object(q, "exists_at", return_value=True), \
             patch.object(q, "safe_git_blob_at", return_value=json.dumps(record)), \
             patch.object(q, "content_fingerprint", return_value="version-2"):
            self.assertIsNone(q.existing_error("sha", item("bad")))

    def test_marker_is_durable_and_never_writes_the_story_or_main_branch(self):
        with patch.object(q, "content_fingerprint", return_value="abcdef"), \
             patch.object(q, "exists_at", return_value=False), \
             patch.object(q.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            written = q.record_article_error("sha", item("bad"), ValueError("Broken cover"))
        self.assertEqual(written["id"], "bad")
        self.assertEqual(written["status"], "blocked_article_validation")
        args = run.call_args.args[0]
        self.assertIn("repos/AfterDark1000/iipike-site/contents/editorial_inbox/release_errors/bad.json", args)
        self.assertIn("branch=editorial-intake", args)
        self.assertFalse(any("articles/" in str(part) for part in args))


if __name__ == "__main__":
    unittest.main()
