"""Offline regression checks for the site-only editorial candidate pool."""
from datetime import datetime, timezone
import copy
import unittest

from scripts.site_news_pool import (
    add, candidate_id, canonical_url, next_item, transition, validate
)

NOW = "2026-11-12T07:00:00+00:00"


def fresh():
    return {"schema_version": 1, "note": "Site candidates only; not a publication queue.",
            "items": []}


def record(title, url, **kwargs):
    return {"title": title, "source_url": url, **kwargs}


class SiteNewsPoolTests(unittest.TestCase):
    def test_empty_file_is_valid(self):
        self.assertEqual(validate(fresh()), fresh())

    def test_batch_is_deduplicated_by_url_and_title(self):
        pool, report = add(fresh(), [
            record("A useful AI story", "https://example.org/story/?utm_source=chat"),
            record("Another title same URL", "https://example.org/story"),
            record("A useful AI story", "https://another.org/story"),
            record("A genuinely different story", "https://example.org/different"),
        ], now=NOW)
        self.assertEqual(len(pool["items"]), 2)
        self.assertEqual(len(report["duplicates"]), 2)
        self.assertEqual(pool["items"][0]["source_url"], "https://example.org/story")
        self.assertEqual(pool["items"][0]["id"], candidate_id("https://example.org/story"))
        self.assertFalse(any(x["status"] != "queued" for x in pool["items"]))

    def test_sources_must_be_valid_https(self):
        for bad in ("http://example.com/a", "https://user:pw@example.org/a",
                    "https://example.com:8080/a", "javascript:alert(1)"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    add(fresh(), [record("A good title", bad)], now=NOW)

    def test_next_selects_priority_then_fifo_and_claims_only_one(self):
        pool, _ = add(fresh(), [
            record("Old normal item", "https://example.org/a"),
            record("Fresh urgent item", "https://example.org/b", priority="high"),
            record("Low priority item", "https://example.org/c", priority="low")
        ], now=NOW)
        claimed_pool, chosen = next_item(pool, now="2026-11-12T08:00:00+00:00")
        self.assertEqual(chosen["title"], "Fresh urgent item")
        self.assertEqual(chosen["status"], "in_review")
        self.assertEqual(sum(x["status"] == "in_review" for x in claimed_pool["items"]), 1)
        self.assertTrue(all(x["status"] == "queued" for x in pool["items"]))
        second_pool, second = next_item(claimed_pool, now="2026-11-12T08:01:00+00:00")
        self.assertEqual(second["title"], "Old normal item")
        self.assertEqual(len(second_pool["items"]), 3)

    def test_repeated_add_does_not_reset_claimed_item(self):
        pool, _ = add(fresh(), [record("Interesting new launch", "https://example.org/a")], now=NOW)
        pool, selected = next_item(pool, now=NOW)
        next_pool, report = add(pool, [
            record("Interesting new launch", "https://example.org/a?utm_campaign=test")
        ], now=NOW)
        self.assertEqual(report["added"], [])
        self.assertEqual(next_pool["items"][0]["status"], "in_review")
        self.assertEqual(selected["id"], next_pool["items"][0]["id"])

    def test_return_and_approve_require_real_article_id(self):
        pool, _ = add(fresh(), [record("Interesting new launch", "https://example.org/a")], now=NOW)
        pool, selected = next_item(pool, now=NOW)
        with self.assertRaises(ValueError):
            transition(pool, selected["id"], "approve", now=NOW)
        returned, item = transition(pool, selected["id"], "return", now=NOW)
        self.assertEqual(item["status"], "queued")
        self.assertIsNone(item["review_started_at"])
        resumed, selected = next_item(returned, now=NOW)
        finished, item = transition(resumed, selected["id"], "approve",
                                    article_id="verified-story-20261112", now=NOW)
        self.assertEqual(item["article_id"], "verified-story-20261112")
        self.assertEqual(item["status"], "approved")
        self.assertEqual(sum(i["status"] == "queued" for i in finished["items"]), 0)

    def test_reject_does_not_create_article(self):
        pool, _ = add(fresh(), [record("Incorrect claim story", "https://example.org/b")], now=NOW)
        pool, selected = next_item(pool, now=NOW)
        pool, item = transition(pool, selected["id"], "reject", note="No primary source", now=NOW)
        self.assertIsNone(item["article_id"])
        self.assertEqual(item["status"], "rejected")
        self.assertIsNone(next_item(pool)[1])

    def test_validation_rejects_duplicate_and_unsafe_state(self):
        pool, _ = add(fresh(), [record("Interesting new launch", "https://example.org/a")], now=NOW)
        damaged = copy.deepcopy(pool)
        damaged["items"].append(copy.deepcopy(damaged["items"][0]))
        with self.assertRaises(ValueError):
            validate(damaged)
        damaged = copy.deepcopy(pool)
        damaged["items"][0]["status"] = "approved"
        with self.assertRaises(ValueError):
            validate(damaged)


if __name__ == "__main__":
    unittest.main()
