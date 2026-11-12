"""One-off recovery must never expand scope or alter normal publication."""
import unittest

from scripts.site_first_catchup_gemini import (
    TARGET, MAX_ARTICLES, MIN_GAP, scope_before_target,
)


class CatchupThroughGeminiTests(unittest.TestCase):
    def test_only_items_up_to_and_including_gemini(self):
        pending = [
            {"id": "older-1"},
            {"id": "older-2"},
            {"id": TARGET},
            {"id": "later-story"},
        ]
        self.assertEqual([x["id"] for x in scope_before_target(pending)],
                         ["older-1", "older-2", TARGET])

    def test_target_is_required_and_never_skip_over_it(self):
        with self.assertRaisesRegex(ValueError, "target absent"):
            scope_before_target([{"id": "other"}])
        self.assertEqual(scope_before_target([{"id": TARGET}]),
                         [{"id": TARGET}])

    def test_no_unbounded_mass_dump(self):
        oversize = [{"id": f"before-{i}"} for i in range(MAX_ARTICLES)]
        oversize.append({"id": TARGET})
        with self.assertRaisesRegex(ValueError, "beyond nine"):
            scope_before_target(oversize)

    def test_every_recovery_release_is_individually_spaced(self):
        self.assertEqual(int(MIN_GAP.total_seconds()), 120)


if __name__ == "__main__":
    unittest.main()
