"""Offline safety checks for racing main commits and stale release branches.

No real git writes, network requests, publishing or workflow dispatch.
"""
from contextlib import ExitStack
from types import SimpleNamespace
import os
import subprocess
import unittest
from unittest.mock import patch

from scripts import site_first_release_pr as pr

SID = "safe-retry-test-story"
SRC = ("editorial_inbox/stories/" + SID + ".json",
       "editorial_inbox/covers/" + SID + ".webp")


class RebuildOnMainDriftTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HPII_SITE_FIRST_AUTOPUBLISH": "1",
            "GITHUB_RUN_ID": "44047326106",
            "GITHUB_RUN_ATTEMPT": "1",
        }))
        self.commands = []
        self.fetch_count = 0
        self.remote_branch = ""
        self.story_already_published = False
        def fake_git(*args, **kwargs):
            self.commands.append(args)
            if args[:2] == ("ls-remote", "--heads"):
                return SimpleNamespace(stdout=self.remote_branch)
            if args[:3] == ("fetch", "origin", "main"):
                self.fetch_count += 1
            if args[:2] == ("rev-parse", "origin/main"):
                return SimpleNamespace(stdout="fresh-base-" + str(self.fetch_count) + "\n")
            return SimpleNamespace(stdout="", returncode=0)
        self.git_mock = self.stack.enter_context(
            patch.object(pr, "git", side_effect=fake_git))
        self.stack.enter_context(patch.object(pr, "pending_paths", return_value=SRC))
        self.stack.enter_context(patch.object(pr, "exists_at",
                                              side_effect=lambda *_: self.story_already_published))
        self.stack.enter_context(patch.object(pr, "transfer_blob"))
        self.checked = self.stack.enter_context(patch.object(pr, "run_checked"))
        self.stack.enter_context(patch.object(pr, "proposed_changes",
                                              return_value=["news.json", f"articles/{SID}/index.html"]))
        self.stack.enter_context(patch.object(pr.subprocess, "run",
                                              return_value=SimpleNamespace(returncode=0)))
        self.publish = self.stack.enter_context(patch.object(pr, "auto_publish_site"))

    def test_existing_canonical_branch_is_preserved_and_rebuilt_from_source(self):
        self.remote_branch = "535d6f old-canonical"
        with patch.dict(pr.LEGACY_RECOVERY_RELEASES, {SID: "535d6f"}):
            result = pr.release_one(SID, "immutable-editorial-sha")
        self.assertEqual(result, "auto_published_rebuild_requested")
        self.publish.assert_called_once_with(SID, "fresh-base-1", SRC)
        self.assertIn(("switch", "--detach", "origin/main"), self.commands)
        self.assertIn(("switch", "-c",
                       f"site-first/auto/{SID}/44047326106-1-1"), self.commands)
        self.assertNotIn(("push", "origin",
                          f"HEAD:refs/heads/site-first/release/{SID}"), self.commands)
        self.assertFalse(any(x[0] in ("reset", "rebase", "cherry-pick", "clean", "branch")
                             for x in self.commands))
        self.assertTrue(any(x[0] == "push" and x[-1].startswith("HEAD:refs/heads/site-first/auto/")
                            for x in self.commands))
        self.assertEqual(self.checked.call_count, 6)  # stage + 4 builders + full tests

    def test_unrelated_main_move_rebuilds_all_artifacts_and_tests(self):
        self.publish.side_effect = [pr.MainMovedDuringRelease("other data changed"), None]
        result = pr.release_one(SID, "immutable-editorial-sha")
        self.assertEqual(result, "auto_published_rebuild_requested")
        self.assertEqual(self.publish.call_count, 2)
        self.assertEqual(self.checked.call_count, 12)
        self.assertEqual([call.args[1] for call in self.publish.call_args_list],
                         ["fresh-base-1", "fresh-base-2"])
        branches = [x[2] for x in self.commands if x[:2] == ("switch", "-c")]
        self.assertEqual(branches, [
            f"site-first/auto/{SID}/44047326106-1-1",
            f"site-first/auto/{SID}/44047326106-1-2",
        ])
        self.assertFalse(any("--force" in x or "--force-with-lease" in x
                             for args in self.commands for x in args))

    def test_three_moving_main_attempts_defer_without_marking_published(self):
        self.publish.side_effect = [
            pr.MainMovedDuringRelease("retry") for _ in range(pr.MAX_AUTO_REBUILDS)]
        self.assertEqual(pr.release_one(SID, "editorial-sha"), "deferred_moving_main")
        self.assertEqual(self.publish.call_count, 3)
        self.assertEqual(self.checked.call_count, 18)
        self.assertEqual(sum(x[:2] == ("switch", "-c") for x in self.commands), 3)

    def test_unrelated_failure_never_retries_or_publishes_another_story(self):
        self.publish.side_effect = ValueError("Unsafe generated file")
        with self.assertRaisesRegex(ValueError, "Unsafe generated file"):
            pr.release_one(SID, "editorial-sha")
        self.publish.assert_called_once()
        self.assertEqual(self.checked.call_count, 6)

    def test_already_published_article_not_restaged(self):
        self.story_already_published = True
        self.assertEqual(pr.release_one(SID, "editorial-sha"), "published")
        self.publish.assert_not_called()
        self.checked.assert_not_called()

    def test_unverified_old_release_branch_cannot_bypass_manual_review(self):
        self.remote_branch = "different-unknown-sha old-manual-review"
        self.assertEqual(pr.release_one(SID, "editorial-sha"), "exists")
        self.publish.assert_not_called()
        self.checked.assert_not_called()

    def test_manual_prepared_branch_keeps_existing_review_protection(self):
        self.remote_branch = "old"
        with patch.dict(os.environ, {"HPII_SITE_FIRST_AUTOPUBLISH": "0"}):
            self.assertEqual(pr.release_one(SID, "editorial-sha"), "exists")
        self.publish.assert_not_called()
        self.checked.assert_not_called()

    def test_run_identity_required_for_unique_non_overwriting_attempts(self):
        with patch.dict(os.environ, {"GITHUB_RUN_ID": ""}):
            with self.assertRaisesRegex(ValueError, "GitHub run identity"):
                pr.release_one(SID, "editorial-sha")
        self.git_mock.assert_called_once()

    def test_sensitive_main_updates_require_new_scheduler_cycle(self):
        self.publish.assert_not_called()
        with patch.object(pr, "git", side_effect=lambda *a, **kw:
                          SimpleNamespace(stdout=("news.json\n" if a[0] == "diff" else ""),
                                          returncode=0)):
            with self.assertRaisesRegex(ValueError, "publishing-sensitive"):
                pr.classify_main_drift("old", "new")
        with patch.object(pr, "git", side_effect=lambda *a, **kw:
                          SimpleNamespace(stdout="", returncode=0)):
            with self.assertRaises(pr.MainMovedDuringRelease):
                pr.classify_main_drift("old", "new")


if __name__ == "__main__":
    unittest.main()
