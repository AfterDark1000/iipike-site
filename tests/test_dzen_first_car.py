import copy
import json
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from dzen_first_car import connect, dzen_snapshot, ingest, mark, queue_snapshot, replay_sequence, timestamp
from dzen_first_car_rss import hints

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "lab" / "dzen-first-car" / "fixtures" / "sequence.json"
NEW = "https://dzen.ru/a/demo000000000006"


class FirstCarPipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "history.db"
        self.db = connect(self.path, replay=True)
        self.addCleanup(self.db.close)
        self.steps = json.loads(FIXTURE.read_bytes())["steps"]

    def test_sequence_detects_once_and_keeps_handled_item_out_of_pending(self):
        steps = replay_sequence(self.db, self.steps)["steps"]
        self.assertEqual([len(s["pending"]) for s in steps], [0, 1, 1, 1, 0, 0])
        self.assertEqual([s["total_offers"] for s in steps], [0, 1, 1, 1, 1, 1])
        self.assertEqual(steps[4]["handled"], {NEW: "commented"})
        self.assertEqual(steps[1]["pending"][0]["views"], 0)
        self.assertEqual(steps[3]["pending"][0]["comments"], 2)
        self.assertEqual(steps[3]["pending"][0]["first_seen_at"], "2026-11-19T10:10:00+00:00")
        self.assertEqual(steps[3]["pending"][0]["offer_at"], steps[1]["as_of"])
        with closing(connect(self.path, replay=True)) as reopened:
            self.assertEqual(queue_snapshot(reopened, timestamp(steps[4]["as_of"]), replay=True)["decisions"],
                             {NEW: "commented"})
        self.assertEqual(queue_snapshot(self.db, timestamp(steps[1]["as_of"]), replay=True)["decisions"], {})

    def test_conflicting_snapshot_is_atomic(self):
        saved = self.steps[0]["snapshot"]
        ingest(self.db, saved, replay=True)
        bad = copy.deepcopy(saved)
        bad["articles"][0]["views"] = 400
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            ingest(self.db, bad, replay=True)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 5)

    def test_stale_snapshot_and_unknown_comments_cannot_enter_queue(self):
        ingest(self.db, self.steps[0]["snapshot"], replay=True)
        fresh = copy.deepcopy(self.steps[1]["snapshot"])
        fresh["articles"][0]["comments"] = None
        ingest(self.db, fresh, replay=True)
        result = queue_snapshot(self.db, timestamp(fresh["observed_at"]), replay=True)
        self.assertEqual(result["channels"][0]["status"], "confirmed_candidate")
        self.assertEqual(result["channels"][0]["history"]["median_views"], 500)
        self.assertEqual(result["articles"], [])
        saved = self.steps[3]["snapshot"]
        ingest(self.db, saved, replay=True)
        later = timestamp("2026-11-19T10:43:00Z")
        self.assertEqual(queue_snapshot(self.db, later, replay=True)["articles"], [])

    def test_source_policies_and_demo_databases_remain_isolated(self):
        with self.assertRaisesRegex(ValueError, "separate databases"):
            connect(self.path)
        with closing(connect(Path(self.temp.name) / "operational.db")) as separate:
            with self.assertRaisesRegex(ValueError, "incompatible"):
                ingest(separate, self.steps[0]["snapshot"])
            raw = {"channel": {"status": "ok", "source": {
                "title": "Контроль", "publisher_id": "0" * 24, "feed_link": "https://dzen.ru/control",
            }}, "items": [{
                "item_type": "native", "publisher_id": "0" * 24, "link": NEW + "?track=x",
                "title": "Новая нейросеть", "publication_date": str(timestamp("2026-11-19T10:00:00Z")),
                "views": 0, "socialInfo": {"commentsEnabled": True, "commentCount": 0},
            }]}
            snapshot = dzen_snapshot(raw, "control", "2026-11-19T10:10:00Z")
            ingest(separate, snapshot)
            self.assertEqual(separate.execute("SELECT url, views, comments, verified FROM observations")
                             .fetchone()[:], (NEW, 0, 0, 0))
            self.assertEqual(queue_snapshot(separate, timestamp(snapshot["observed_at"]))["articles"], [])

    def test_rss_hint_is_deduplicated_and_remains_outside_article_history(self):
        xml = b"""<rss><channel><item><title>New Apple Intelligence feature</title>
                 <link>https://example.org/article</link><guid>1</guid>
                 <description>Background: https://dzen.ru/a/demo000000000006</description>
                 <pubDate>Thu, 19 Nov 2026 10:00:00 +0000</pubDate></item></channel></rss>"""
        at = timestamp("2026-11-19T10:10:00Z")
        result = hints(self.db, "control", "https://example.org/feed", xml, at)
        self.assertTrue(result["request_hint"])
        self.assertFalse(result["confirmed_on_dzen"])
        self.assertNotIn("dzen_url", result["new_publisher_items"][0])
        self.assertFalse(hints(self.db, "control", "https://example.org/feed", xml, at)["request_hint"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM articles").fetchone()[0], 0)

    def test_atom_dzen_alternate_is_a_hint_only_and_omitted_if_ambiguous(self):
        at = timestamp("2026-11-19T10:10:00Z")
        for extra, expected in (("", NEW), ('<link href="https://dzen.ru/a/demo000000000007"/>', None)):
            xml = f"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
                <title>New Apple Intelligence feature</title>
                <link rel="alternate" href="https://example.org/article"/>
                <link rel="alternate" href="{NEW}?share_to=link"/>{extra}
                <published>2026-11-19T10:00:00Z</published></entry></feed>""".encode()
            with closing(connect(":memory:")) as db:
                result = hints(db, "control", "https://example.org/feed", xml, at)
                self.assertFalse(result["confirmed_on_dzen"])
                item = result["new_publisher_items"][0]
                self.assertEqual(item.get("dzen_url"), expected)
                self.assertEqual(item["publisher_published_at"], "2026-11-19T10:00:00+00:00")
                self.assertEqual(queue_snapshot(db, at)["articles"], [])

    def test_skip_persists_until_an_explicit_undo(self):
        for step in self.steps[:2]:
            ingest(self.db, step["snapshot"], replay=True)
        now = timestamp("2026-11-19T10:10:00Z")
        queue_snapshot(self.db, now, replay=True)
        mark(self.db, NEW, "skipped", now)
        self.assertEqual(queue_snapshot(self.db, now, replay=True)["decisions"], {NEW: "skipped"})
        mark(self.db, NEW, "undo", now)
        self.assertEqual(queue_snapshot(self.db, now, replay=True)["decisions"], {})


if __name__ == "__main__":
    unittest.main()
