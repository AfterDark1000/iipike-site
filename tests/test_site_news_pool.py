"""Offline regression checks for the site-only editorial candidate pool."""
from datetime import datetime, timezone
import copy
import unittest

from scripts.site_news_pool import (
    add, candidate_id, canonical_url, next_item, continue_item, local_date,
    transition, validate
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
        self.assertEqual([x["sequence"] for x in pool["items"]], [1, 2])
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

    def test_next_obeys_strict_fifo_regardless_of_priority_and_claims_one(self):
        pool, _ = add(fresh(), [
            record("Old normal item", "https://example.org/a"),
            record("Fresh urgent item", "https://example.org/b", priority="high"),
            record("Low priority item", "https://example.org/c", priority="low")
        ], now=NOW)
        claimed_pool, chosen = next_item(pool, now="2026-11-12T08:00:00+00:00")
        self.assertEqual(chosen["title"], "Old normal item")
        self.assertEqual(chosen["sequence"], 1)
        self.assertEqual(chosen["status"], "in_review")
        self.assertEqual(sum(x["status"] == "in_review" for x in claimed_pool["items"]), 1)
        self.assertTrue(all(x["status"] == "queued" for x in pool["items"]))
        second_pool, second = next_item(claimed_pool, now="2026-11-12T08:01:00+00:00")
        self.assertEqual(second["title"], "Fresh urgent item")
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(len(second_pool["items"]), 3)
        self.assertEqual([x["sequence"] for x in second_pool["items"]], [1, 2, 3])

    def test_batch_preserves_explicit_selection_order_across_chat_batches(self):
        first, _ = add(fresh(), [
            record("First item in first chat", "https://example.org/a"),
            record("Second item in first chat", "https://example.org/b"),
        ], now=NOW)
        later, _ = add(first, [
            record("First item in second chat", "https://example.org/c"),
            record("Second item in second chat", "https://example.org/d"),
        ], now=NOW)
        self.assertEqual([i["sequence"] for i in later["items"]], [1, 2, 3, 4])
        self.assertEqual([i["title"] for i in later["items"]],
                         ["First item in first chat", "Second item in first chat",
                          "First item in second chat", "Second item in second chat"])

    def test_continue_is_read_only_and_keeps_original_reservation_date(self):
        pool, _ = add(fresh(), [
            record("Old held item", "https://example.org/a"),
            record("Another held item", "https://example.org/b")
        ], now=NOW)
        pool, first = next_item(pool, now="2026-11-12T08:00:00+00:00")
        pool, second = next_item(pool, now="2026-11-12T09:00:00+00:00")
        before = copy.deepcopy(pool)
        resumed = continue_item(pool)
        self.assertEqual(resumed["id"], first["id"])
        self.assertEqual(resumed["review_started_at"], "2026-11-12T08:00:00+00:00")
        self.assertEqual(continue_item(pool, item_id=second["id"])["id"], second["id"])
        self.assertIsNone(continue_item(pool, item_id="n-fake"))
        self.assertEqual(pool, before)
        self.assertEqual(local_date("2026-11-12T08:00:00+00:00"),
                         "12.11.2026 13:00 (+05+0500)")

    def test_return_goes_back_to_original_fifo_position(self):
        pool, _ = add(fresh(), [
            record("Old first item", "https://example.org/a"),
            record("Later second item", "https://example.org/b")
        ], now=NOW)
        pool, selected = next_item(pool, now=NOW)
        pool, _ = transition(pool, selected["id"], "return", now=NOW)
        self.assertEqual(next_item(pool, now=NOW)[1]["id"], selected["id"])
        self.assertEqual(pool["items"][0]["sequence"], 1)

    def test_incorrect_sequence_is_rejected(self):
        pool, _ = add(fresh(), [
            record("Some news title", "https://example.org/a"),
            record("Another news title", "https://example.org/b")
        ], now=NOW)
        broken = copy.deepcopy(pool)
        broken["items"][1]["sequence"] = 1
        with self.assertRaises(ValueError):
            validate(broken)

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
