"""Regression tests for human-directed emergency site-first publication."""
import datetime as dt
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.site_first_release_intent import (
    KICK_PATH, REQUEST_PATH, verify_push_intent,
)
from scripts.site_publication_queue import main as queue_main

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 5, 10, 20, tzinfo=UTC)
BEFORE, AFTER = ("a" * 40, "b" * 40)
SID = "safe-news-20261105"


def event(message, branch="refs/heads/main"):
    return {
        "repository": {"full_name": "AfterDark1000/iipike-site"},
        "ref": branch,
        "before": BEFORE,
        "after": AFTER,
        "head_commit": {"message": message},
    }


def git_fake(path):
    def git(*args):
        if args == ("rev-parse", "HEAD"):
            return AFTER
        if args == ("diff", "--name-only", BEFORE, AFTER):
            return path
        raise AssertionError("unexpected Git command " + str(args))
    return git


def source(requested_at="2026-11-05T10:19:00Z",
           story_id=SID, urgent=True):
    return json.dumps({
        "story_id": story_id, "urgent": urgent,
        "requested_at": requested_at,
    })


class UserUrgentIntentTests(unittest.TestCase):
    def test_one_fresh_matching_urgent_request(self):
        e = event("hpii: [hpii-urgent-release] " + SID)
        self.assertEqual(
            verify_push_intent(e, now=NOW, git_cmd=git_fake(REQUEST_PATH),
                               read=lambda *args, **kw: source()),
            ("urgent", SID),
        )

    def test_normal_queue_kick_preserves_hourly_spacing(self):
        e = event("chore: [hpii-queue-kick] release one due story")
        self.assertEqual(
            verify_push_intent(e, now=NOW, git_cmd=git_fake(KICK_PATH)),
            ("queue", ""),
        )

    def test_wrong_branch_or_repo_cannot_trigger(self):
        e = event("hpii: [hpii-urgent-release] " + SID,
                  branch="refs/heads/editorial-intake")
        with self.assertRaisesRegex(ValueError, "main branch"):
            verify_push_intent(e, now=NOW, git_cmd=git_fake(REQUEST_PATH))
        e = event("hpii: [hpii-urgent-release] " + SID)
        e["repository"]["full_name"] = "someone/else"
        with self.assertRaisesRegex(ValueError, "Unexpected repository"):
            verify_push_intent(e, now=NOW, git_cmd=git_fake(REQUEST_PATH))

    def test_no_urgent_if_changed_files_are_not_exact_control_file(self):
        e = event("hpii: [hpii-urgent-release] " + SID)
        for path in ("editorial_inbox/stories/" + SID + ".json",
                     REQUEST_PATH + "\nREADME.md", KICK_PATH):
            with self.subTest(path=path), self.assertRaisesRegex(
                    ValueError, "standalone urgent"):
                verify_push_intent(e, now=NOW, git_cmd=git_fake(path))

    def test_reject_missing_marker_or_mismatched_id(self):
        for message, payload in [
            ("Publish urgently " + SID, source()),
            ("hpii: [hpii-urgent-release] " + SID, source(story_id="other")),
            ("hpii: [hpii-urgent-release] ../escape", source()),
            ("hpii: [hpii-urgent-release] " + SID, source(urgent=False)),
        ]:
            with self.subTest(message=message, payload=payload), \
                 self.assertRaises(ValueError):
                verify_push_intent(
                    event(message), now=NOW, git_cmd=git_fake(REQUEST_PATH),
                    read=lambda *args, **kw: payload,
                )

    def test_expired_or_future_urgent_command_cannot_replay(self):
        e = event("hpii: [hpii-urgent-release] " + SID)
        for at in ("2026-11-05T09:30:00Z", "2026-11-05T10:24:00Z"):
            with self.subTest(at=at), self.assertRaisesRegex(ValueError, "expired"):
                verify_push_intent(
                    e, now=NOW, git_cmd=git_fake(REQUEST_PATH),
                    read=lambda *args, **kw: source(requested_at=at),
                )

    def test_checkout_must_be_exact_pushed_commit(self):
        e = event("hpii: [hpii-urgent-release] " + SID)
        with self.assertRaisesRegex(ValueError, "pushed commit"):
            verify_push_intent(
                e, now=NOW,
                git_cmd=lambda *args: BEFORE, read=lambda *args, **kw: source(),
            )

    def test_emergency_push_requires_verified_env_not_cron_or_regular_push(self):
        env = {
            "GITHUB_REPOSITORY": "AfterDark1000/iipike-site",
            "HPII_SITE_FIRST_SCHEDULER": "1",
            "HPII_SITE_FIRST_AUTOPUBLISH": "1",
            "HPII_TARGET_STORY_ID": SID,
            "HPII_URGENT_STORY": "true",
            "GITHUB_EVENT_NAME": "push",
            "HPII_VERIFIED_PUSH_URGENT": "false",
        }
        with patch.dict("os.environ", env):
            with self.assertRaisesRegex(ValueError, "verified"):
                queue_main()

    def test_verified_urgent_push_selects_one_exact_article(self):
        env = {
            "GITHUB_REPOSITORY": "AfterDark1000/iipike-site",
            "HPII_SITE_FIRST_SCHEDULER": "1",
            "HPII_SITE_FIRST_AUTOPUBLISH": "1",
            "HPII_TARGET_STORY_ID": SID,
            "HPII_URGENT_STORY": "true",
            "GITHUB_EVENT_NAME": "push",
            "HPII_VERIFIED_PUSH_URGENT": "true",
            "HPII_QUEUE_INSPECT_ONLY": "false",
        }
        selected = {"id": SID, "ready_at": NOW - dt.timedelta(hours=1),
                    "not_before": NOW + dt.timedelta(hours=3),
                    "cover": "editorial_inbox/covers/" + SID + ".webp"}
        with patch.dict("os.environ", env), \
             patch("scripts.site_publication_queue.git",
                   return_value=SimpleNamespace(stdout="source-sha")), \
             patch("scripts.site_publication_queue.safe_git_blob_at",
                   return_value="[]"), \
             patch("scripts.site_publication_queue.ready_items",
                   return_value=[selected]), \
             patch("scripts.site_publication_queue.select_one",
                   return_value=selected) as choose, \
             patch("scripts.site_publication_queue.release_one",
                   return_value="auto_published_rebuild_requested") as release:
            queue_main()
            self.assertEqual(choose.call_args.kwargs["urgent"], True)
            self.assertEqual(choose.call_args.kwargs["target"], SID)
            release.assert_called_once_with(SID, "source-sha")


if __name__ == "__main__":
    unittest.main()
