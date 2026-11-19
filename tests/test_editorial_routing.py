"""Unit tests for triage routing; independent of live editorial files."""
import copy
import tempfile
from pathlib import Path
import unittest

from scripts.site_news_pool import add, next_item, validate as validate_pool
from scripts.auto_editor_workbench import claim_ordinary
from scripts.editorial_routing import (
    validate_document, next_short, claim_short, long_allowed
)

NOW = "2026-11-19T05:00:00+00:00"


def fixture():
    src = {"schema_version": 1, "note": "Test only.", "items": []}
    records = [
        {"title": "Short factual story", "source_url": "https://example.org/s", "priority": "normal"},
        {"title": "Hold for human decision", "source_url": "https://example.org/h", "priority": "normal"},
        {"title": "Hot important story", "source_url": "https://example.org/a", "priority": "high"},
        {"title": "Ordinary long story", "source_url": "https://example.org/l", "priority": "normal"},
    ]
    pool, _ = add(src, records, now=NOW)
    rows = pool["items"]
    routes = {
        rows[0]["id"]: {"pool_id": rows[0]["id"], "sequence": 1, "lane": "short", "decision": "short"},
        rows[1]["id"]: {"pool_id": rows[1]["id"], "sequence": 2, "lane": "hold", "decision": "defer"},
        rows[2]["id"]: {"pool_id": rows[2]["id"], "sequence": 3, "lane": "long", "decision": "hot"},
        rows[3]["id"]: {"pool_id": rows[3]["id"], "sequence": 4, "lane": "long", "decision": "full"},
    }
    return pool, routes


class RoutingTests(unittest.TestCase):
    def test_full_editor_skips_short_and_hold(self):
        pool, routes = fixture()
        original = copy.deepcopy(pool)
        updated, selected = next_item(pool, now=NOW, routing=routes)
        self.assertEqual(selected["sequence"], 3)
        self.assertEqual(updated["items"][0]["status"], "queued")
        self.assertEqual(updated["items"][1]["status"], "queued")
        self.assertEqual(pool, original)

    def test_auto_editor_skips_short_and_hold_and_hot(self):
        pool, routes = fixture()
        updated, ticket = claim_ordinary(pool, "test-routing-01.json", now=NOW, routing=routes)
        self.assertEqual(ticket["pool_sequence"], 4)
        self.assertEqual(updated["items"][3]["status"], "in_review")
        self.assertEqual(updated["items"][0]["status"], "queued")

    def test_short_editor_claims_only_short_and_blocks_other_editor(self):
        pool, routes = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            updated, selected = claim_short(pool, routes=routes, root=Path(tmp), now=NOW)
            self.assertEqual(selected["sequence"], 1)
            self.assertTrue(selected["note"].startswith("SHORT_EDITOR claim=short"))
            validate_pool(updated)
            self.assertIsNone(next_short(updated, routes=routes, root=Path(tmp)))
            after, long_item = next_item(updated, now=NOW, routing=routes)
            self.assertEqual(long_item["sequence"], 3)
            self.assertEqual(after["items"][0]["status"], "in_review")

    def test_short_candidate_dedup(self):
        pool, routes = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(next_short(
                pool, routes=routes, root=root, exclude_ids=[pool["items"][0]["id"]]
            ))

    def test_reject_mismatch_and_duplicate_routes(self):
        pool, routes = fixture()
        base = {
            "schema_version": 1, "approved_date": "2026-11-19",
            "source": "data/editorial_triage/test.json", "source_pool_sha": "test",
            "note": "Test only", "items": list(routes.values())
        }
        self.assertEqual(len(validate_document(base, pool)), 4)
        corrupted = copy.deepcopy(base)
        corrupted["items"][0]["sequence"] = 99
        with self.assertRaisesRegex(ValueError, "mismatch"):
            validate_document(corrupted, pool)
        duplicated = copy.deepcopy(base)
        duplicated["items"].append(duplicated["items"][0])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_document(duplicated, pool)

    def test_unrouted_future_news_defaults_to_long(self):
        pool, routes = fixture()
        self.assertTrue(long_allowed({"id": "n-0000000000000000"}, routes))


if __name__ == "__main__":
    unittest.main()
