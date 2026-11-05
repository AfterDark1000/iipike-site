"""Offline tests: no immediate publication and precisely one due article per run."""
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.site_publication_queue import (
    INTERVAL, latest_site_first_publication, parse_slot, ready_items,
    select_one, main,
)

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 5, 8, 0, tzinfo=UTC)


def item(sid, hour, *, slot=None):
    return {"id": sid,
            "ready_at": dt.datetime(2026, 11, 5, hour, 0, tzinfo=UTC),
            "not_before": slot, "cover": f"editorial_inbox/covers/{sid}.webp"}


class PublicationQueueTests(unittest.TestCase):
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
                   return_value="[]"), \
             patch("scripts.site_publication_queue.ready_items",
                   return_value=[selected, item("second", 6)]), \
             patch("scripts.site_publication_queue.select_one",
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
