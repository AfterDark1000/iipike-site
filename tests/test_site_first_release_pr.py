"""Offline tests for site-first intake release proposal; no GitHub calls or site writes."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from scripts.site_first_release_pr import changed_ids, pending_paths, candidate_ids_from_tree

ID = "news-example-20261104"


class SiteFirstReleaseSelectionTests(unittest.TestCase):
    def test_only_exact_named_inbox_paths_are_candidates(self):
        event = {
            "commits": [
                {"added": [f"editorial_inbox/stories/{ID}.json", "README.md",
                           "editorial_inbox/stories/../evil.json",
                           "editorial_inbox/stories/UPPERCASE.json"],
                 "modified": [f"editorial_inbox/covers/{ID}.webp",
                              f"editorial_inbox/covers/{ID}.png",
                              "editorial_inbox/stories/.gitkeep"]},
            ]
        }
        self.assertEqual(changed_ids(event), [ID])

    def test_push_without_changed_files_recovers_real_committed_story_and_cover(self):
        self.assertEqual(changed_ids({"commits": []}), [])
        tree = "\n".join([
            "editorial_inbox/stories/news-example-20261104.json",
            "editorial_inbox/covers/news-example-20261104.webp",
            "editorial_inbox/stories/.gitkeep",
            "editorial_inbox/covers/OTHER.webp",
        ]) + "\n"
        with patch("scripts.site_first_release_pr.git",
                   return_value=SimpleNamespace(stdout=tree)) as g:
            self.assertEqual(candidate_ids_from_tree("a-real-commit-sha"), [ID])
            g.assert_called_once()

    def test_tree_scan_can_find_cover_sent_in_separate_later_commit(self):
        tree = "editorial_inbox/stories/news-example-20261104.json\n"
        with patch("scripts.site_first_release_pr.git",
                   return_value=SimpleNamespace(stdout=tree)):
            self.assertEqual(candidate_ids_from_tree("sha"), [ID])

    def test_one_editorial_text_or_one_cover_is_not_a_release(self):
        with patch("scripts.site_first_release_pr.exists_at", side_effect=lambda ref, p: p.endswith(".json")):
            self.assertIsNone(pending_paths("HEAD", ID))
        with patch("scripts.site_first_release_pr.exists_at", return_value=False):
            self.assertIsNone(pending_paths("HEAD", ID))

    def test_stable_story_id_requires_exactly_one_original_image(self):
        with patch("scripts.site_first_release_pr.exists_at",
                   side_effect=lambda ref,p: p.endswith(".json") or p.endswith(".webp")):
            self.assertEqual(pending_paths("HEAD", ID),
                             (f"editorial_inbox/stories/{ID}.json",
                              f"editorial_inbox/covers/{ID}.webp"))
        with patch("scripts.site_first_release_pr.exists_at",
                   side_effect=lambda ref,p: p.endswith(".json") or p.endswith(".webp") or p.endswith(".png")):
            with self.assertRaisesRegex(ValueError, "Ambiguous"):
                pending_paths("HEAD", ID)

    def test_explicit_retry_fails_closed_for_invalid_id(self):
        event = {"inputs": {"story_id": "foo/../../.github/workflows"}}
        with self.assertRaisesRegex(ValueError, "Invalid"):
            changed_ids(event)

    def test_unrelated_path_never_triggers_a_real_publication(self):
        self.assertEqual(changed_ids({"commits":[{"added":["editorial_inbox/covers/.gitkeep"]}]}), [])


if __name__ == "__main__":
    unittest.main()
