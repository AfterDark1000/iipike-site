"""Offline tests: no immediate publication and precisely one due article per run."""
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.site_publication_queue import (
    INTERVAL, RECOVERY_INTERVAL, release_interval,
    latest_site_first_publication, parse_slot, ready_items,
    select_one, main, _last_change, published_collision, without_published_collisions,
)

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 5, 8, 0, tzinfo=UTC)


def item(sid, hour, *, slot=None):
    return {"id": sid,
            "ready_at": dt.datetime(2026, 11, 5, hour, 0, tzinfo=UTC),
            "not_before": slot, "cover": f"editorial_inbox/covers/{sid}.webp"}


class PublicationQueueTests(unittest.TestCase):
    def test_temporary_recovery_stops_at_gemini_not_at_backlog_size(self):
        now = dt.datetime(2026, 11, 12, 8, 0, tzinfo=UTC)
        target = "google-gemini-for-healthcare-20261110"
        self.assertEqual(release_interval(now, 10, [target]), dt.timedelta(minutes=30))
        self.assertEqual(release_interval(now, 10, ["other"]), INTERVAL)
        self.assertEqual(release_interval(now, 50), INTERVAL)
        self.assertEqual(release_interval(
            dt.datetime(2026, 11, 15, 8, tzinfo=UTC), 50, [target]), INTERVAL)
        pending = [
            {"id": "ready-" + str(i),
             "ready_at": now - dt.timedelta(hours=2),
             "not_before": None,
             "cover": "editorial_inbox/covers/ready-" + str(i) + ".webp"}
            for i in range(10)
        ]
        pending[-1]["id"] = target
        with patch("scripts.site_publication_queue.latest_site_first_publication",
                   return_value=now - dt.timedelta(minutes=35)):
            self.assertEqual(select_one(pending, [], now)["id"], "ready-0")
            self.assertIsNone(select_one(pending[:9], [], now))
        self.assertEqual(RECOVERY_INTERVAL, dt.timedelta(minutes=30))

    def test_distinct_stories_sharing_a_primary_source_are_not_filtered(self):
        already = [{
            "id": "published-story",
            "title": "Already published title",
            "source_url": "https://example.org/common",
        }]
        pending = [item("same-source", 2), item("same-title", 3), item("next-valid", 4)]
        same_source = {"title": "A different headline",
                       "source_url": "https://example.org/common"}
        same_title = {"title": "ALREADY PUBLISHED TITLE",
                      "source_url": "https://example.org/different"}
        unique = {"title": "Completely new article",
                  "source_url": "https://example.org/unique"}
        def blob(_ref, path):
            if "same-source.json" in path:
                return json.dumps(same_source)
            if "same-title.json" in path:
                return json.dumps(same_title)
            return json.dumps(unique)
        with patch("scripts.site_publication_queue.safe_git_blob_at", side_effect=blob):
            remaining = without_published_collisions(pending, already, source_ref="test-ref")
        self.assertEqual([row["id"] for row in remaining], ["same-source", "next-valid"])
        self.assertIsNone(published_collision(same_source, already))
        self.assertEqual(published_collision(same_title, already)["id"], "published-story")
        self.assertIsNone(published_collision(unique, already))

    def test_case_insensitive_duplicate_title_is_blocked(self):
        existing = [{"id": "one", "title": "A Unique Story", "source_url": "https://a.test/a"}]
        candidate = {"title": "a unique story", "source_url": "https://b.test/b"}
        self.assertEqual(published_collision(candidate, existing)["id"], "one")

    def test_queue_position_survives_a_technical_correction(self):
        """Original arrival time, not a later Markdown/cover fix, determines order."""
        original = "2026-11-05T04:00:00+00:00"
        corrected = "2026-11-05T08:40:00+00:00"

        def fake_git(*args):
            if "--diff-filter=A" in args:
                return SimpleNamespace(stdout=original + "\n")
            return SimpleNamespace(stdout=corrected + "\n")

        with patch("scripts.site_publication_queue.git", side_effect=fake_git):
            self.assertEqual(_last_change("origin/editorial-intake", "editorial_inbox/stories/old.json"),
                             dt.datetime(2026, 11, 5, 4, tzinfo=UTC))

    def test_malformed_markdown_does_not_block_other_ready_stories(self):
        tree = "\n".join([
            "editorial_inbox/stories/bad.json", "editorial_inbox/covers/bad.webp",
            "editorial_inbox/stories/good.json", "editorial_inbox/covers/good.webp",
        ])
        malformed = "Вступление для теста. " * 30 + "\n\n>Неверная цитата"
        def fake_source(ref, path):
            sid = Path(path).stem
            result = {"id": sid, "status": "editor_approved",
                      "approved_by": "human_editor"}
            if sid == "bad":
                result["article_markdown"] = malformed
            return json.dumps(result)

        with patch("scripts.site_publication_queue.git",
                   return_value=SimpleNamespace(stdout=tree)), \
             patch("scripts.site_publication_queue.exists_at", return_value=False), \
             patch("scripts.site_publication_queue.safe_git_blob_at", side_effect=fake_source), \
             patch("scripts.site_publication_queue._last_change",
                   return_value=NOW - dt.timedelta(hours=2)), \
             patch("builtins.print") as log:
            found = ready_items()
        self.assertEqual([row["id"] for row in found], ["good"])
        self.assertTrue(any(c.args and c.args[0] == "BLOCKED_INVALID_MARKDOWN:"
                            for c in log.call_args_list))

    def test_night_pause_uses_yekaterinburg_local_time_boundaries(self):
        """00:59 works; 01:00–06:59 waits; 07:00 works again."""
        local = dt.timezone(dt.timedelta(hours=5))
        article = {
            "id": "overnight", "ready_at": dt.datetime(2026, 11, 7, 12, tzinfo=UTC),
            "not_before": None, "cover": "editorial_inbox/covers/overnight.webp",
        }
        with patch("scripts.site_publication_queue.latest_site_first_publication",
                   return_value=None):
            for hour, minute, allowed in [
                (0, 59, True), (1, 0, False), (3, 30, False),
                (6, 59, False), (7, 0, True), (23, 59, True),
            ]:
                when = dt.datetime(2026, 11, 8, hour, minute, tzinfo=local)
                with self.subTest(hour=hour, minute=minute):
                    found = select_one([article], [], when)
                    self.assertEqual(found is not None, allowed)

    def test_explicit_night_slot_does_not_bypass_pause(self):
        local = dt.timezone(dt.timedelta(hours=5))
        article = {
            "id": "late", "ready_at": dt.datetime(2026, 11, 7, 12, tzinfo=UTC),
            "not_before": dt.datetime(2026, 11, 8, 2, tzinfo=local),
            "cover": "editorial_inbox/covers/late.webp",
        }
        with patch("scripts.site_publication_queue.latest_site_first_publication",
                   return_value=None):
            self.assertIsNone(select_one([article], [],
                                        dt.datetime(2026, 11, 8, 3, tzinfo=local)))
            self.assertEqual(select_one([article], [],
                                        dt.datetime(2026, 11, 8, 7, tzinfo=local))["id"], "late")

    def test_exact_urgent_request_may_bypass_night_pause(self):
        local = dt.timezone(dt.timedelta(hours=5))
        now = dt.datetime(2026, 11, 8, 3, 0, tzinfo=local)
        article = {
            "id": "urgent-overnight", "ready_at": now - dt.timedelta(hours=1),
            "not_before": now + dt.timedelta(hours=8),
            "cover": "editorial_inbox/covers/urgent-overnight.webp",
        }
        with patch("scripts.site_publication_queue.latest_site_first_publication",
                   return_value=now - dt.timedelta(minutes=10)):
            self.assertIsNone(select_one([article], [], now, target="urgent-overnight"))
            self.assertEqual(select_one([article], [], now, target="urgent-overnight",
                                        urgent=True)["id"], "urgent-overnight")

    def test_strict_yekaterinburg_schedule(self):
        at = parse_slot("2026-11-06T11:00:00+05:00")
        self.assertEqual(at, dt.datetime(2026, 11, 6, 6, tzinfo=UTC))
        for raw in ("2026-11-06T11:00:00Z", "2026-11-06T11:00:00",
                    "2026-11-06T11:00:00+03:00", "2026-02-30T11:00:00+05:00",
                    "../../evil", 123, None):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_slot(raw)

    def test_queue_sorts_by_last_ready_component_and_skips_published(self):
        tree = "\n".join([
            "editorial_inbox/stories/older.json",
            "editorial_inbox/covers/older.webp",
            "editorial_inbox/stories/newer.json",
            "editorial_inbox/covers/newer.webp",
            "editorial_inbox/stories/published.json",
            "editorial_inbox/covers/published.webp",
        ])
        def fake_git(*args, **kwargs):
            self.assertEqual(args[0], "ls-tree")
            return SimpleNamespace(stdout=tree)

        def fake_exists(ref, path):
            return ref == "origin/main" and "published" in path

        def fake_source(ref, path):
            sid = Path(path).stem
            return json.dumps({"id": sid, "status": "editor_approved",
                               "approved_by": "human_editor"})

        def fake_change(ref, path):
            if "older" in path:
                return NOW - dt.timedelta(hours=4)
            return NOW - dt.timedelta(hours=2)

        with patch("scripts.site_publication_queue.git", side_effect=fake_git), \
             patch("scripts.site_publication_queue.exists_at", side_effect=fake_exists), \
             patch("scripts.site_publication_queue.safe_git_blob_at",
                   side_effect=fake_source), \
             patch("scripts.site_publication_queue._last_change",
                   side_effect=fake_change):
            found = ready_items()
        self.assertEqual([x["id"] for x in found], ["older", "newer"])

    def test_unverified_dzen_link_isolated_from_other_ready_stories(self):
        tree = "\n".join([
            "editorial_inbox/stories/blocking.json",
            "editorial_inbox/covers/blocking.webp",
            "editorial_inbox/stories/clean.json",
            "editorial_inbox/covers/clean.webp",
        ])
        bad_ref = "6aec0bd5c4df40737eced1fa"
        def fake_source(ref, path):
            sid = Path(path).stem
            return json.dumps({
                "id": sid, "status": "editor_approved",
                "approved_by": "human_editor",
                "related_dzen_ids": [bad_ref] if sid == "blocking" else [],
            })
        def fake_git(*args, **kwargs):
            self.assertEqual(args[0], "ls-tree")
            return SimpleNamespace(stdout=tree)
        with patch("scripts.site_publication_queue.git", side_effect=fake_git), \
             patch("scripts.site_publication_queue.exists_at", return_value=False), \
             patch("scripts.site_publication_queue.safe_git_blob_at",
                   side_effect=fake_source), \
             patch("scripts.site_publication_queue._last_change",
                   return_value=NOW - dt.timedelta(hours=2)), \
             patch("scripts.site_publication_queue.catalog_entries",
                   return_value={}), \
             patch("builtins.print") as output:
            ready = ready_items()
        self.assertEqual([row["id"] for row in ready], ["clean"])
        self.assertTrue(any(
            call.args and call.args[0] == "BLOCKED_UNVERIFIED_DZEN_REFERENCE:"
            for call in output.call_args_list))

    def test_valid_optional_dzen_crosslink_still_passes_full_validator(self):
        tree = ("editorial_inbox/stories/safe.json\n"
                "editorial_inbox/covers/safe.webp\n")
        refid = "6ae9af0cc44bda2203fe42ae"
        data = json.dumps({"id": "safe", "status": "editor_approved",
                           "approved_by": "human_editor",
                           "related_dzen_ids": [refid]})
        with patch("scripts.site_publication_queue.git",
                   return_value=SimpleNamespace(stdout=tree)), \
             patch("scripts.site_publication_queue.exists_at",
                   return_value=False), \
             patch("scripts.site_publication_queue.safe_git_blob_at",
                   return_value=data), \
             patch("scripts.site_publication_queue._last_change",
                   return_value=NOW - dt.timedelta(hours=2)), \
             patch("scripts.site_publication_queue.catalog_entries",
                   return_value={refid: {"dzen_id": refid, "title": "Verified",
                                        "url_evidence": "recorded_in_editorial_archive",
                                        "title_evidence": "recorded",
                                        "dzen_url": "https://dzen.ru/a/aumvDMRL2iID_kKu"}}):
            ready = ready_items()
        self.assertEqual([x["id"] for x in ready], ["safe"])

    def test_missing_cover_is_not_eligible_for_release(self):
        with patch("scripts.site_publication_queue.git",
                   return_value=SimpleNamespace(
                       stdout="editorial_inbox/stories/not-ready.json\n")), \
             patch("scripts.site_publication_queue.exists_at", return_value=False):
            self.assertEqual(ready_items(), [])

    def test_unapproved_story_fails_closed(self):
        tree = ("editorial_inbox/stories/fake.json\n"
                "editorial_inbox/covers/fake.webp\n")
        with patch("scripts.site_publication_queue.git",
                   return_value=SimpleNamespace(stdout=tree)), \
             patch("scripts.site_publication_queue.exists_at", return_value=False), \
             patch("scripts.site_publication_queue.safe_git_blob_at",
                   return_value=json.dumps({"id": "fake", "status": "draft",
                                            "approved_by": "human_editor"})):
            with self.assertRaisesRegex(ValueError, "Unapproved"):
                ready_items()

    def test_spacing_one_hour_and_at_most_one_due(self):
        items = [item("first", 5), item("second", 6)]
        with patch("scripts.site_publication_queue.latest_site_first_publication",
                   return_value=NOW - dt.timedelta(minutes=59)):
            self.assertIsNone(select_one(items, [], NOW))
        with patch("scripts.site_publication_queue.latest_site_first_publication",
                   return_value=NOW - dt.timedelta(minutes=60)):
            self.assertEqual(select_one(items, [], NOW)["id"], "first")
        with patch("scripts.site_publication_queue.latest_site_first_publication",
                   return_value=NOW - dt.timedelta(hours=2)):
            self.assertEqual(select_one(items, [], NOW)["id"], "first")
        self.assertEqual(INTERVAL, dt.timedelta(hours=1))

    def test_future_slot_delays_one_item_not_entire_queue(self):
        later = NOW + dt.timedelta(hours=5)
        items = [item("delayed", 4, slot=later), item("ready", 6)]
        with patch("scripts.site_publication_queue.latest_site_first_publication",
                   return_value=None):
            self.assertEqual(select_one(items, [], NOW)["id"], "ready")
            self.assertEqual(select_one(items, [], later)["id"], "delayed")

    def test_emergency_requires_explicit_id_and_manual_event(self):
        items = [item("future", 5, slot=NOW + dt.timedelta(hours=10))]
        with patch("scripts.site_publication_queue.latest_site_first_publication",
                   return_value=NOW - dt.timedelta(minutes=5)):
            self.assertIsNone(select_one(items, [], NOW, target="future"))
            self.assertEqual(
                select_one(items, [], NOW, target="future", urgent=True)["id"], "future")
            with self.assertRaisesRegex(ValueError, "exact editorial"):
                select_one(items, [], NOW, urgent=True)
            with self.assertRaisesRegex(ValueError, "Invalid exact"):
                select_one(items, [], NOW, target="../other", urgent=True)
            with self.assertRaisesRegex(ValueError, "not approved"):
                select_one(items, [], NOW, target="nonexistent")

    def test_only_real_site_first_entries_set_spacing(self):
        rows = [
            {"id": "historical", "published_at_utc": "2026-11-05T07:59:00Z"},
            {"id": "newstory", "published_at_utc": "2026-11-05T05:00:00Z"},
        ]
        def fake_exists(ref, path):
            return path == "editorial_inbox/stories/newstory.json"
        with patch("scripts.site_publication_queue.exists_at", side_effect=fake_exists):
            self.assertEqual(latest_site_first_publication(rows),
                             dt.datetime(2026, 11, 5, 5, tzinfo=UTC))

    def test_queue_does_not_publish_when_not_due(self):
        with patch.dict("os.environ", {
                "GITHUB_REPOSITORY": "AfterDark1000/iipike-site",
                "HPII_SITE_FIRST_SCHEDULER": "1",
                "HPII_SITE_FIRST_AUTOPUBLISH": "1",
                "HPII_TARGET_STORY_ID": "",
                "HPII_URGENT_STORY": "false",
                "GITHUB_EVENT_NAME": "schedule"}), \
             patch("scripts.site_publication_queue.git",
                   return_value=SimpleNamespace(stdout="source-ref")), \
             patch("scripts.site_publication_queue.safe_git_blob_at",
                   return_value="[]"), \
             patch("scripts.site_publication_queue.ready_items", return_value=[]), \
             patch("scripts.site_publication_queue.select_one", return_value=None), \
             patch("scripts.site_publication_queue.release_one") as release:
            main()
            release.assert_not_called()

    def test_no_more_than_one_release_even_when_many_ready(self):
        selected = item("first", 5)
        with patch.dict("os.environ", {
                "GITHUB_REPOSITORY": "AfterDark1000/iipike-site",
                "HPII_SITE_FIRST_SCHEDULER": "1",
                "HPII_SITE_FIRST_AUTOPUBLISH": "1",
                "HPII_TARGET_STORY_ID": "",
                "HPII_URGENT_STORY": "false",
                "GITHUB_EVENT_NAME": "schedule"}), \
             patch("scripts.site_publication_queue.git",
                   return_value=SimpleNamespace(stdout="source-ref")), \
             patch("scripts.site_publication_queue.safe_git_blob_at",
                   side_effect=lambda ref, path: (
                       "[]" if path == "news.json" else
                       json.dumps({"title": "Pending valid story",
                                   "source_url": "https://example.test/story"})
                   )), \
             patch("scripts.site_publication_queue.ready_items",
                   return_value=[selected, item("second", 6)]), \
             patch("scripts.site_publication_queue.select_publishable_item",
                   return_value=selected), \
             patch("scripts.site_publication_queue.release_one",
                   return_value="auto_published_rebuild_requested") as release:
            main()
            release.assert_called_once_with("first", "source-ref")

    def test_manual_override_cannot_be_triggered_by_cron(self):
        with patch.dict("os.environ", {
                "GITHUB_REPOSITORY": "AfterDark1000/iipike-site",
                "HPII_SITE_FIRST_SCHEDULER": "1",
                "HPII_SITE_FIRST_AUTOPUBLISH": "1",
                "HPII_TARGET_STORY_ID": "first",
                "HPII_URGENT_STORY": "true",
                "GITHUB_EVENT_NAME": "schedule"}):
            with self.assertRaisesRegex(ValueError, "manual"):
                main()


if __name__ == "__main__":
    unittest.main()
