"""Offline tests for the GitHub-side news intake bridge (no network, no publishing)."""
from pathlib import Path
import json
import subprocess
import tempfile
import unittest

from scripts.site_news_intake import apply_pending, request_order
from scripts.site_news_pool import candidate_id, validate, next_item


class NewsIntakeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.requests = self.root / "data/site_news_intake/requests"
        self.receipts = self.root / "data/site_news_intake/receipts"
        self.requests.mkdir(parents=True)
        self.pool = self.root / "data/site_news_pool.json"
        self.pool.write_text(json.dumps({
            "schema_version": 1, "note": "Test only: candidate pool", "items": [],
        }), encoding="utf-8")

    def write(self, name, records, **extra):
        p = self.requests / name
        p.write_text(json.dumps({"schema_version": 1, "records": records, **extra},
                                ensure_ascii=False), encoding="utf-8")
        return p

    def read_pool(self):
        value = json.loads(self.pool.read_text(encoding="utf-8"))
        validate(value)
        return value

    def receipt(self, name):
        return json.loads((self.receipts / name).read_text(encoding="utf-8"))

    def test_import_preserves_order_and_same_source_can_have_two_stories(self):
        path = self.write("20261116-081500-first.json", [
            {"title": "Первый независимый сюжет про ИИ", "source_url": "https://example.org/a?utm_source=chat",
             "summary": "First", "origin": "test", "priority": "normal"},
            {"title": "Второй независимый сюжет про ИИ", "source_url": "https://example.org/a",
             "summary": "Second", "origin": "test", "priority": "high"},
        ])
        result = apply_pending(self.root, [path])
        self.assertEqual(result["added_count"], 2)
        self.assertEqual(result["queued_total"], 2)
        pool = self.read_pool()
        self.assertEqual([x["sequence"] for x in pool["items"]], [1, 2])
        self.assertEqual(pool["items"][0]["id"], candidate_id("https://example.org/a"))
        self.assertEqual(pool["items"][1]["id"],
                         candidate_id("https://example.org/a", "Второй независимый сюжет про ИИ"))
        self.assertEqual(pool["items"][0]["source_url"], "https://example.org/a")
        self.assertEqual(next_item(pool)[1]["sequence"], 2)
        self.assertEqual(self.receipt(path.name)["status"], "imported")

    def test_idempotent_after_receipt_and_duplicate_title_skipped(self):
        p = self.write("20261116-081600-twice.json", [
            {"title": "Первая новость о модели", "source_url": "https://example.org/a"},
            {"title": "Первая новость о модели", "source_url": "https://example.org/b"},
        ])
        first = apply_pending(self.root, [p])
        self.assertEqual(first["added_count"], 1)
        self.assertEqual(first["duplicates_count"], 1)
        before = self.pool.read_bytes()
        second = apply_pending(self.root, [p])
        self.assertEqual(second["processed_requests"], 0)
        self.assertEqual(self.pool.read_bytes(), before)
        self.assertEqual(self.receipt(p.name)["duplicates"], ["Первая новость о модели"])

    def test_rejected_batch_does_not_block_following_request(self):
        bad = self.write("20261116-081700-bad.json", [
            {"title": "Attempt to inject a status", "source_url": "https://example.org/b",
             "status": "approved"},
        ])
        good = self.write("20261116-081701-good.json", [
            {"title": "Good news with safe URL", "source_url": "https://example.org/good"},
        ])
        report = apply_pending(self.root, [bad, good])
        self.assertEqual(report["rejected_requests"], 1)
        self.assertEqual(report["added_count"], 1)
        self.assertEqual(self.receipt(bad.name)["status"], "rejected")
        self.assertEqual(self.receipt(good.name)["status"], "imported")
        self.assertEqual(len(self.read_pool()["items"]), 1)
        follow = apply_pending(self.root, [bad, good])
        self.assertEqual(follow["processed_requests"], 0)

    def test_reject_unknown_schema_without_modifying_pool(self):
        p = self.write("20261116-081800-schema.json", [
            {"title": "Unknown schema change", "source_url": "https://example.org/a"},
        ], secret_field="something")
        report = apply_pending(self.root, [p])
        self.assertEqual(report["rejected_requests"], 1)
        self.assertEqual(len(self.read_pool()["items"]), 0)
        self.assertIn("schema_version", self.receipt(p.name)["error"])

    def test_refuses_to_reuse_modified_request_after_receipt(self):
        p = self.write("20261116-081900-once.json", [
            {"title": "Original news title", "source_url": "https://example.org/a"},
        ])
        apply_pending(self.root, [p])
        original = self.pool.read_bytes()
        self.write(p.name, [
            {"title": "Tampered new title", "source_url": "https://example.org/other"},
        ])
        with self.assertRaisesRegex(ValueError, "Already processed request was changed"):
            apply_pending(self.root, [p])
        self.assertEqual(self.pool.read_bytes(), original)

    def test_existing_reserved_item_is_unchanged(self):
        first = self.write("20261116-082000-old.json", [
            {"title": "Older story in review", "source_url": "https://example.org/old"},
        ])
        apply_pending(self.root, [first])
        original = self.read_pool()
        original, _ = next_item(original, now="2026-11-16T03:25:00+00:00")
        self.pool.write_text(json.dumps(original), encoding="utf-8")
        later = self.write("20261116-082001-new.json", [
            {"title": "New independent news", "source_url": "https://example.org/new"},
        ])
        apply_pending(self.root, [first, later])
        updated = self.read_pool()
        self.assertEqual(updated["items"][0], original["items"][0])
        self.assertEqual(updated["items"][1]["sequence"], 2)

    def test_git_creation_order_overrides_request_filenames(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "test@example.org"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Test"], check=True)
        self.write("z-last-name.json", [
            {"title": "Earlier committed item", "source_url": "https://example.org/first"},
        ])
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "first"], check=True)
        self.write("a-first-name.json", [
            {"title": "Later committed item", "source_url": "https://example.org/second"},
        ])
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "second"], check=True)
        ordered = request_order(self.root)
        self.assertEqual([p.name for p in ordered], ["z-last-name.json", "a-first-name.json"])
        apply_pending(self.root)
        self.assertEqual([x["title"] for x in self.read_pool()["items"]],
                         ["Earlier committed item", "Later committed item"])


if __name__ == "__main__":
    unittest.main()
