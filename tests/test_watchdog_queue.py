import datetime as dt
import json
import unittest
from unittest.mock import patch
from scripts import watchdog_queue as w

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 6, 10, 0, tzinfo=UTC)

class SnapshotTests(unittest.TestCase):
    def setUp(self):
        scoped = patch.object(w, "existing_error", return_value=None)
        scoped.start()
        self.addCleanup(scoped.stop)

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


    def test_backlog_only_its_actual_hourly_slots_can_be_overdue(self):
        local = dt.timezone(dt.timedelta(hours=5))
        last = dt.datetime(2026, 11, 11, 8, 15, tzinfo=local)
        ready = dt.datetime(2026, 11, 9, 15, 0, tzinfo=local)
        pending = [
            {'id': 'dimension9-claude-live-horror-game-20261106',
             'ready_at': ready, 'not_before': None},
            {'id': 'ioan-gruffudd-ai-deepfake-romance-20261109',
             'ready_at': ready + dt.timedelta(minutes=1), 'not_before': None},
            {'id': 'anthropic-fable-mythos-52-black-holes-20261109',
             'ready_at': ready + dt.timedelta(minutes=2), 'not_before': None},
            {'id': 'anthropic-claude-agents-os-eight-days-20261109',
             'ready_at': ready + dt.timedelta(minutes=3), 'not_before': None},
            {'id': 'meta-muse-ember-agents-pricing-20261109',
             'ready_at': ready + dt.timedelta(minutes=4), 'not_before': None},
        ]
        now = dt.datetime(2026, 11, 11, 11, 5, tzinfo=local)
        overdue = w.overdue_publications(pending, last, now)
        self.assertEqual(overdue, [{
            'id': 'dimension9-claude-live-horror-game-20261106',
            'minutes': 103,
        }])
        self.assertNotIn('anthropic-fable-mythos-52-black-holes-20261109',
                         [r['id'] for r in overdue])
        self.assertNotIn('anthropic-claude-agents-os-eight-days-20261109',
                         [r['id'] for r in overdue])
        self.assertNotIn('meta-muse-ember-agents-pricing-20261109',
                         [r['id'] for r in overdue])

    def test_watchdog_anchors_to_oldest_ready_not_sliding_dashboard(self):
        local = dt.timezone(dt.timedelta(hours=5))
        last = dt.datetime(2026, 11, 11, 8, 15, tzinfo=local)
        ready = dt.datetime(2026, 11, 9, 15, 0, tzinfo=local)
        pending = [
            {'id': 'first', 'ready_at': ready, 'not_before': None},
            {'id': 'second', 'ready_at': ready, 'not_before': None},
            {'id': 'future', 'ready_at': ready,
             'not_before': dt.datetime(2026, 11, 11, 21, 0, tzinfo=local)},
        ]
        before = dt.datetime(2026, 11, 11, 10, 30, tzinfo=local)
        self.assertEqual(w.overdue_publications(pending, last, before), [])
        after = dt.datetime(2026, 11, 11, 12, 13, tzinfo=local)
        overdue = w.overdue_publications(pending, last, after)
        self.assertEqual(overdue, [
            {'id': 'first', 'minutes': 171},
            {'id': 'second', 'minutes': 111},
        ])
        self.assertNotIn('future', [row['id'] for row in overdue])

    def test_overnight_future_story_never_receives_false_delay(self):
        local = dt.timezone(dt.timedelta(hours=5))
        ready = dt.datetime(2026, 11, 10, 22, 0, tzinfo=local)
        last = dt.datetime(2026, 11, 10, 23, 15, tzinfo=local)
        pending = [
            {'id': 'night-future', 'ready_at': ready,
             'not_before': dt.datetime(2026, 11, 11, 8, 0, tzinfo=local)}
        ]
        at_night = dt.datetime(2026, 11, 11, 3, 0, tzinfo=local)
        self.assertEqual(w.overdue_publications(pending, last, at_night), [])
        before_dawn = dt.datetime(2026, 11, 11, 8, 22, tzinfo=local)
        self.assertEqual(w.overdue_publications(pending, last, before_dawn), [])

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
        self.assertEqual(result['overdue'], [{'id':'overdue-one', 'minutes':233}])

if __name__ == '__main__':
    unittest.main()
