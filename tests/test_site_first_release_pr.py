"""Offline tests for site-first intake release proposal; no GitHub calls or site writes."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from scripts.site_first_release_pr import changed_ids, pending_paths, candidate_ids_from_tree, proposed_changes, auto_publish_site

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

    def test_release_diff_skips_only_generated_bytecode(self):
        porcelain = "\n".join([
            "?? scripts/__pycache__/editorial_draft.cpython-312.pyc",
            "?? tests/__pycache__/test_site_first_inbox.cpython-312.pyc",
            "?? __pycache__/script.cpython-312.pyc",
            " M index.html",
            "?? assets/editorial/image.webp",
        ]) + "\n"
        with patch("scripts.site_first_release_pr.git",
                   return_value=SimpleNamespace(stdout=porcelain)):
            self.assertEqual(proposed_changes(), ["index.html", "assets/editorial/image.webp"])

    def test_release_diff_still_blocks_unexpected_generated_or_executable_files(self):
        for path in ("scripts/tmp.log", "scripts/__pycache__/evil.sh",
                     "README.md", ".github/workflows/unauthorized.yml"):
            with self.subTest(path=path):
                with patch("scripts.site_first_release_pr.git",
                           return_value=SimpleNamespace(stdout="?? " + path + "\n")):
                    with self.assertRaisesRegex(ValueError, "Unexpected modified file"):
                        proposed_changes()

    def test_automatic_site_release_only_fast_forwards_exact_approved_artifacts(self):
        sid = ID
        story = f"editorial_inbox/stories/{sid}.json"
        cover = f"editorial_inbox/covers/{sid}.webp"
        all_paths = [
            story, cover, f"assets/editorial/{sid}.webp",
            f"content/approved/{sid}.json", f"articles/{sid}/index.html",
            "news.json", "feed.xml", "sitemap.xml", "index.html",
            "articles/index.html", "rubrics/news/index.html",
        ]
        calls = []

        def fake_git(*args, **kwargs):
            calls.append(args)
            if args[0] == "diff":
                return SimpleNamespace(stdout="\n".join(all_paths) + "\n")
            if args[0] == "rev-parse":
                return SimpleNamespace(stdout="safe-main-base\n")
            return SimpleNamespace(stdout="")

        with patch("scripts.site_first_release_pr.git", side_effect=fake_git), \
             patch("scripts.site_first_release_pr.run_checked") as rebuild:
            auto_publish_site(sid, "safe-main-base", (story, cover))
        self.assertIn(("push", "origin", "HEAD:refs/heads/main"), calls)
        rebuild.assert_called_once_with(
            "gh", "api", "-X", "POST",
            "repos/AfterDark1000/iipike-site/pages/builds"
        )

    def test_auto_release_accepts_only_preexisting_approved_html_refresh(self):
        sid = ID
        story = f"editorial_inbox/stories/{sid}.json"
        cover = f"editorial_inbox/covers/{sid}.webp"
        valid = [
            story, cover, f"assets/editorial/{sid}.webp",
            f"content/approved/{sid}.json", f"articles/{sid}/index.html",
            "news.json", "feed.xml", "sitemap.xml", "index.html",
            "articles/index.html",
        ]
        old_slug = "deepseek-shutdown-override"
        old_page = f"articles/{old_slug}/index.html"
        old_source = f"content/approved/{old_slug}.json"
        calls = []

        def fake_git(*args, **kwargs):
            calls.append(args)
            if args[0] == "diff":
                return SimpleNamespace(stdout="\\n".join(valid + [old_page]) + "\\n")
            if args[0] == "ls-tree":
                requested = args[-1]
                if requested in (old_page, old_source):
                    return SimpleNamespace(stdout=f"100644 blob abcdef\\t{requested}\\n")
                return SimpleNamespace(stdout="")
            if args[0] == "rev-parse":
                return SimpleNamespace(stdout="approved-base\\n")
            return SimpleNamespace(stdout="")

        with patch("scripts.site_first_release_pr.git", side_effect=fake_git), \\
             patch("scripts.site_first_release_pr.run_checked"):
            auto_publish_site(sid, "approved-base", (story, cover))
        self.assertIn(("push", "origin", "HEAD:refs/heads/main"), calls)

        for missing in (old_page, old_source):
            def missing_blob(*args, **kwargs):
                if args[0] == "ls-tree" and args[-1] == missing:
                    return SimpleNamespace(stdout="")
                return fake_git(*args, **kwargs)
            with patch("scripts.site_first_release_pr.git", side_effect=missing_blob), \\
                 patch("scripts.site_first_release_pr.run_checked") as pages:
                with self.assertRaisesRegex(ValueError, "non-editorial"):
                    auto_publish_site(sid, "approved-base", (story, cover))
            pages.assert_not_called()

    def test_automatic_release_fails_closed_for_unexpected_file_or_moving_main(self):
        sid = ID
        story = f"editorial_inbox/stories/{sid}.json"
        cover = f"editorial_inbox/covers/{sid}.webp"
        valid = [
            story, cover, f"assets/editorial/{sid}.webp",
            f"content/approved/{sid}.json", f"articles/{sid}/index.html",
            "news.json", "feed.xml", "sitemap.xml", "index.html",
            "articles/index.html",
        ]
        for extra in ("README.md", ".github/workflows/unreviewed.yml",
                      "assets/editorial/other-story.webp"):
            with self.subTest(extra=extra):
                with patch("scripts.site_first_release_pr.git",
                           return_value=SimpleNamespace(stdout="\n".join(valid + [extra]))):
                    with self.assertRaisesRegex(ValueError, "non-editorial"):
                        auto_publish_site(sid, "base", (story, cover))
        calls = []
        def fake_git(*args, **kwargs):
            calls.append(args)
            if args[0] == "diff":
                return SimpleNamespace(stdout="\n".join(valid))
            if args[0] == "rev-parse":
                return SimpleNamespace(stdout="someone-else-pushed\n")
            return SimpleNamespace(stdout="")
        with patch("scripts.site_first_release_pr.git", side_effect=fake_git), \
             patch("scripts.site_first_release_pr.run_checked") as pages:
            with self.assertRaisesRegex(ValueError, "Main moved"):
                auto_publish_site(sid, "old-base", (story, cover))
        self.assertNotIn(("push", "origin", "HEAD:refs/heads/main"), calls)
        pages.assert_not_called()

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
