import datetime as dt
import json
import unittest
from unittest.mock import patch
from scripts import watchdog_queue as w

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 6, 10, 0, tzinfo=UTC)

class SnapshotTests(unittest.TestCase):
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
