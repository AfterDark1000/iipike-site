import datetime as dt
import json
import unittest
from unittest.mock import patch
from scripts import watchdog_queue as w

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 6, 10, 0, tzinfo=UTC)

class SnapshotTests(unittest.TestCase):
    def test_night_is_not_counted_as_overdue_publication_time(self):
        local = dt.timezone(dt.timedelta(hours=5))
        start = dt.datetime(2026, 11, 8, 0, 50, tzinfo=local)
        night = dt.datetime(2026, 11, 8, 3, 0, tzinfo=local)
        morning = dt.datetime(2026, 11, 8, 8, 0, tzinfo=local)
        self.assertAlmostEqual(w.active_publication_minutes(start, night), 10)
        self.assertAlmostEqual(w.active_publication_minutes(start, morning), 70)
        self.assertLess(w.active_publication_minutes(start, morning), 100)

    @patch.object(w, 'exists_at', return_value=True)
    @patch.object(w, 'ready_items')
    @patch.object(w, 'latest_site_first_publication')
    @patch.object(w, 'safe_git_blob_at')
    @patch.object(w, 'git')
    def test_precise_publication_evidence_contains_main_article_id(self, git, blob, last, ready, exists):
        blob.return_value = json.dumps([
            {'id': 'published-one', 'published_at_utc': '2026-11-06T09:30:00Z'}
        ])
        last.return_value = dt.datetime(2026, 11, 6, 9, 30, tzinfo=UTC)
        ready.return_value = []
        snap = w.snapshot(NOW)
        self.assertEqual(snap['published_site_first'],
                         [{'id':'published-one', 'published_at_utc':'2026-11-06T09:30:00+00:00'}])
        self.assertEqual(snap['blocked_invalid_markdown_ids'], [])
        self.assertTrue(any('articles/published-one/index.html' in call.args
                            for call in exists.call_args_list))

    @patch.object(w, 'exists_at', return_value=True)
    @patch.object(w, 'ready_items')
    @patch.object(w, 'latest_site_first_publication')
    @patch.object(w, 'safe_git_blob_at')
    @patch.object(w, 'git')
    def test_future_and_spacing_are_respected(self, git, blob, last, ready, exists):
        blob.return_value = json.dumps([{'id': 'published-one', 'published_at_utc': '2026-11-06T09:30:00Z'}])
        last.return_value = dt.datetime(2026, 11, 6, 9, 30, tzinfo=UTC)
        ready.return_value = [
            {'id': 'queue-one', 'ready_at': dt.datetime(2026, 11, 5, tzinfo=UTC), 'not_before': None},
            {'id': 'future', 'ready_at': dt.datetime(2026, 11, 5, tzinfo=UTC),
             'not_before': dt.datetime(2026, 11, 6, 12, tzinfo=UTC)},
        ]
        result = w.snapshot(NOW)
        self.assertEqual(result['overdue'], [])
        self.assertEqual(result['newest_id'], 'published-one')

    @patch.object(w, 'exists_at', return_value=True)
    @patch.object(w, 'ready_items')
    @patch.object(w, 'latest_site_first_publication')
    @patch.object(w, 'safe_git_blob_at')
    @patch.object(w, 'git')
    def test_unreleased_eligible_stories_trigger_alert(self, git, blob, last, ready, exists):
        blob.return_value = json.dumps([{'id': 'published-one', 'published_at_utc': '2026-11-06T05:00:00Z'}])
        last.return_value = dt.datetime(2026, 11, 6, 5, tzinfo=UTC)
        ready.return_value = [{'id': 'overdue-one', 'ready_at': dt.datetime(2026, 11, 6, 6, tzinfo=UTC), 'not_before': None}]
        result = w.snapshot(NOW)
        self.assertEqual(result['overdue'], [{'id':'overdue-one', 'minutes':240}])

if __name__ == '__main__':
    unittest.main()
