"""Regression: an old release branch must not block following ready stories.

These are offline tests: no GitHub writes, publication, or Pages deployment.
"""
from contextlib import ExitStack
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.site_publication_queue import main


def row(story_id):
    return {"id": story_id, "cover": f"editorial_inbox/covers/{story_id}.webp"}


class ExistingBranchDoesNotBlockQueue(unittest.TestCase):
    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.env = {
            "GITHUB_REPOSITORY": "AfterDark1000/iipike-site",
            "HPII_SITE_FIRST_SCHEDULER": "1",
            "HPII_SITE_FIRST_AUTOPUBLISH": "1",
            "HPII_TARGET_STORY_ID": "",
            "HPII_URGENT_STORY": "false",
            "HPII_QUEUE_INSPECT_ONLY": "false",
            "GITHUB_EVENT_NAME": "schedule",
        }
        self.context.enter_context(patch.dict("os.environ", self.env))
        self.context.enter_context(patch("scripts.site_publication_queue.git",
                                         return_value=SimpleNamespace(stdout="editorial-sha")))
        self.context.enter_context(patch("scripts.site_publication_queue.safe_git_blob_at",
                                         return_value=json.dumps([])))
        self.context.enter_context(patch("scripts.site_publication_queue.ready_items",
                                         return_value=[row("blocked"), row("next"), row("third")]))
        self.context.enter_context(patch(
            "scripts.site_publication_queue.without_published_collisions",
            side_effect=lambda items, *_args, **_kwargs: items))
        self.select = self.context.enter_context(patch(
            "scripts.site_publication_queue.select_publishable_item",
            side_effect=lambda items, *_args, **_kwargs: items[0] if items else None))
        self.release = self.context.enter_context(patch(
            "scripts.site_publication_queue.release_one"))

    def test_existing_release_branch_skipped_and_next_publishes_once(self):
        self.release.side_effect = ["exists", "auto_published_rebuild_requested"]
        with patch("builtins.print") as output:
            main()
        self.assertEqual([x.args[0] for x in self.release.call_args_list],
                         ["blocked", "next"])
        self.assertEqual(self.select.call_count, 2)
        remaining = self.select.call_args_list[1].args[0]
        self.assertEqual([x["id"] for x in remaining], ["next", "third"])
        self.assertTrue(any("EXISTING_RELEASE_BRANCH_SKIPPED" in str(c.args)
                            for c in output.call_args_list))
        self.assertTrue(any("ONE_RELEASE_REQUESTED:" in str(c.args)
                            for c in output.call_args_list))

    def test_all_collisions_fail_loudly_instead_of_reporting_green(self):
        self.release.side_effect = ["exists", "exists", "exists"]
        with self.assertRaisesRegex(ValueError, "No safe alternative due"):
            main()
        self.assertEqual(self.release.call_count, 3)

    def test_exact_target_never_falls_through_to_unrequested_story(self):
        self.env["HPII_TARGET_STORY_ID"] = "blocked"
        # patch.dict captured a separate dict at context entry.
        with patch.dict("os.environ", {"HPII_TARGET_STORY_ID": "blocked"}):
            self.release.return_value = "exists"
            with self.assertRaisesRegex(ValueError, "refusing to publish an unrelated"):
                main()
        self.release.assert_called_once_with("blocked", "editorial-sha")

    def test_unknown_release_outcome_still_fails_closed(self):
        self.release.return_value = "waiting"
        with self.assertRaisesRegex(ValueError, "not confirmed: waiting"):
            main()
        self.release.assert_called_once_with("blocked", "editorial-sha")

    def test_success_does_not_release_second_story(self):
        self.release.return_value = "auto_published_rebuild_requested"
        main()
        self.release.assert_called_once_with("blocked", "editorial-sha")


if __name__ == "__main__":
    unittest.main()
