"""Offline tests for site-first intake release proposal; no GitHub calls or site writes."""
import unittest
import os
from contextlib import ExitStack
from unittest.mock import patch
from types import SimpleNamespace
from scripts import site_first_release_pr as pr

from scripts.site_first_release_pr import changed_ids, pending_paths, candidate_ids_from_tree, proposed_changes, auto_publish_site

ID = "news-example-20261104"


class SiteFirstReleaseSelectionTests(unittest.TestCase):
    def test_entity_registry_and_pages_are_known_release_outputs(self):
        from scripts.site_first_release_pr import proposed_changes
        class Result:
            stdout = (" M data/entity_registry.json\n"
                      " M entities/index.html\n"
                      " M entities/companies/google/index.html\n")
        with patch("scripts.site_first_release_pr.git", return_value=Result()):
            paths = proposed_changes()
        self.assertIn("data/entity_registry.json", paths)
        self.assertIn("entities/companies/google/index.html", paths)


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
            "news.json", "feed.xml", "dzen-rss.xml", "sitemap.xml", "index.html",
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

    def test_auto_release_accepts_only_byte_identical_approved_inline_image(self):
        sid = ID
        story = f"editorial_inbox/stories/{sid}.json"
        cover = f"editorial_inbox/covers/{sid}.webp"
        source = f"editorial_inbox/illustrations/{sid}/checklist.webp"
        public = f"assets/editorial/inline/{sid}/checklist.webp"
        valid = [
            story, cover, source, public, f"assets/editorial/{sid}.webp",
            f"content/approved/{sid}.json", f"articles/{sid}/index.html",
            "news.json", "feed.xml", "sitemap.xml", "index.html",
            "articles/index.html",
        ]
        calls = []

        def fake_git(*args, **kwargs):
            calls.append(args)
            if args[0] == "diff":
                return SimpleNamespace(stdout="\n".join(valid) + "\n")
            if args[0] == "rev-parse":
                if args[1].startswith("HEAD:"):
                    return SimpleNamespace(stdout="same-blob-sha\n")
                return SimpleNamespace(stdout="base\n")
            return SimpleNamespace(stdout="")

        with patch("scripts.site_first_release_pr.git", side_effect=fake_git), \
             patch("scripts.site_first_release_pr.run_checked"):
            auto_publish_site(sid, "base", (story, cover, source))
        self.assertIn(("push", "origin", "HEAD:refs/heads/main"), calls)
        self.assertIn(("rev-parse", "HEAD:" + source), calls)
        self.assertIn(("rev-parse", "HEAD:" + public), calls)

        # A copy of a different byte sequence must never be auto-published.
        def changed_copy(*args, **kwargs):
            if args == ("rev-parse", "HEAD:" + public):
                return SimpleNamespace(stdout="different-sha\n")
            return fake_git(*args, **kwargs)
        with patch("scripts.site_first_release_pr.git", side_effect=changed_copy), \
             patch("scripts.site_first_release_pr.run_checked") as pages:
            with self.assertRaisesRegex(ValueError, "differs from approved source"):
                auto_publish_site(sid, "base", (story, cover, source))
        pages.assert_not_called()

    def test_auto_release_rejects_unapproved_inline_paths(self):
        sid = ID
        story = f"editorial_inbox/stories/{sid}.json"
        cover = f"editorial_inbox/covers/{sid}.webp"
        good = f"editorial_inbox/illustrations/{sid}/checklist.webp"
        valid = [
            story, cover, f"assets/editorial/{sid}.webp",
            f"content/approved/{sid}.json", f"articles/{sid}/index.html",
            "news.json", "feed.xml", "sitemap.xml", "index.html",
            "articles/index.html",
        ]
        for bad in ("editorial_inbox/illustrations/other-story/extra.webp",
                    "editorial_inbox/illustrations/" + sid + "/../../README.md"):
            with self.subTest(bad=bad), \
                 patch("scripts.site_first_release_pr.git") as git_call:
                with self.assertRaisesRegex(ValueError, "unapproved illustration"):
                    auto_publish_site(sid, "base", (story, cover, bad))
                git_call.assert_not_called()

        # Even a story-scoped public asset is forbidden unless the source was
        # explicitly referenced and included in the approved editor markup.
        extra = f"assets/editorial/inline/{sid}/unexpected.webp"
        with patch("scripts.site_first_release_pr.git",
                   return_value=SimpleNamespace(stdout="\n".join(valid + [extra]) + "\n")):
            with self.assertRaisesRegex(ValueError, "non-editorial"):
                auto_publish_site(sid, "base", (story, cover))

    def test_auto_release_accepts_only_preexisting_approved_html_refresh(self):
        sid = ID
        story = f"editorial_inbox/stories/{sid}.json"
        cover = f"editorial_inbox/covers/{sid}.webp"
        valid = [
            story, cover, f"assets/editorial/{sid}.webp",
            f"content/approved/{sid}.json", f"articles/{sid}/index.html",
            "news.json", "feed.xml", "dzen-rss.xml", "sitemap.xml", "index.html",
            "articles/index.html",
        ]
        old_slug = "deepseek-shutdown-override"
        old_page = f"articles/{old_slug}/index.html"
        old_source = f"content/approved/{old_slug}.json"
        calls = []

        def fake_git(*args, **kwargs):
            calls.append(args)
            if args[0] == "diff":
                return SimpleNamespace(stdout="\n".join(valid + [old_page]) + "\n")
            if args[0] == "ls-tree":
                requested = args[-1]
                if requested in (old_page, old_source):
                    return SimpleNamespace(stdout=f"100644 blob abcdef\t{requested}\n")
                return SimpleNamespace(stdout="")
            if args[0] == "rev-parse":
                return SimpleNamespace(stdout="approved-base\n")
            return SimpleNamespace(stdout="")

        with patch("scripts.site_first_release_pr.git", side_effect=fake_git), \
             patch("scripts.site_first_release_pr.run_checked"):
            auto_publish_site(sid, "approved-base", (story, cover))
        self.assertIn(("push", "origin", "HEAD:refs/heads/main"), calls)

        for missing in (old_page, old_source):
            def missing_blob(*args, **kwargs):
                if args[0] == "ls-tree" and args[-1] == missing:
                    return SimpleNamespace(stdout="")
                return fake_git(*args, **kwargs)
            with patch("scripts.site_first_release_pr.git", side_effect=missing_blob), \
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
            "news.json", "feed.xml", "dzen-rss.xml", "sitemap.xml", "index.html",
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
        source = '{"paragraphs":[{"type":"lead","text":"Описание"},'
        source += '{"type":"p","text":"Продолжение"}]}'
        with patch("scripts.site_first_release_pr.safe_git_blob_at", return_value=source):
            with patch("scripts.site_first_release_pr.exists_at",
                       side_effect=lambda ref,p: p.endswith(".json") or p.endswith(".webp")):
                self.assertEqual(pending_paths("HEAD", ID),
                                 (f"editorial_inbox/stories/{ID}.json",
                                  f"editorial_inbox/covers/{ID}.webp"))
            with patch("scripts.site_first_release_pr.exists_at",
                       side_effect=lambda ref,p: p.endswith(".json") or p.endswith(".webp") or p.endswith(".png")):
                with self.assertRaisesRegex(ValueError, "Ambiguous"):
                    pending_paths("HEAD", ID)

    def test_missing_story_illustration_is_a_safe_wait(self):
        source = ('{"paragraphs":[{"type":"lead","text":"Вступление"},'
                  '{"type":"image","src":"illustrations/' + ID +
                  '/checklist.webp","alt":"Проверка звонка"},'
                  '{"type":"p","text":"Основные шаги"}]}')
        with patch("scripts.site_first_release_pr.safe_git_blob_at", return_value=source):
            with patch("scripts.site_first_release_pr.exists_at",
                       side_effect=lambda ref,p: p.endswith(".json") or
                                                  p.endswith("covers/" + ID + ".webp")):
                self.assertIsNone(pending_paths("HEAD", ID))
            with patch("scripts.site_first_release_pr.exists_at",
                       side_effect=lambda ref,p: p.endswith(".json") or
                                                  p.endswith("covers/" + ID + ".webp") or
                                                  p.endswith("illustrations/" + ID + "/checklist.webp")):
                self.assertEqual(pending_paths("HEAD", ID),
                                 (f"editorial_inbox/stories/{ID}.json",
                                  f"editorial_inbox/covers/{ID}.webp",
                                  f"editorial_inbox/illustrations/{ID}/checklist.webp"))

    def test_explicit_retry_fails_closed_for_invalid_id(self):
        event = {"inputs": {"story_id": "foo/../../.github/workflows"}}
        with self.assertRaisesRegex(ValueError, "Invalid"):
            changed_ids(event)

    def test_unrelated_path_never_triggers_a_real_publication(self):
        self.assertEqual(changed_ids({"commits":[{"added":["editorial_inbox/covers/.gitkeep"]}]}), [])


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
