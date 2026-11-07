"""Regression: verified Dzen catalog sync may extend links but never lose evidence."""
import copy
import json
from pathlib import Path
import unittest

from scripts.site_related import canonical_dzen_url, verified, validate_reference
from scripts.sync_editorial_catalog_snapshot import blob_sha, merge_snapshot

ROOT = Path(__file__).resolve().parents[1]
CATHEDRAL_ID = "6aeab653728a9a2a9edd2968"


class VerifiedCatalogSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads((ROOT / "data" / "editorial_full_catalog_snapshot.json").read_text(encoding="utf-8"))

    def test_canonical_cathedral_link_is_now_trusted(self):
        items = {x["dzen_id"]: x for x in self.snapshot["entries"]}
        item = validate_reference(CATHEDRAL_ID, items)
        self.assertIn("OpenAI", item["title"])
        self.assertEqual(item["dzen_url"], "https://dzen.ru/a/auq2U3KKmiqe3Slo")
        self.assertTrue(all(verified(x) for x in items.values()))

    def test_upstream_loss_of_title_does_not_delete_old_link(self):
        old = copy.deepcopy(self.snapshot)
        incoming = copy.deepcopy(old["entries"][:150])
        ident = incoming[0]["dzen_id"]
        incoming[0]["title"] = None
        merged = merge_snapshot(old, {"schema_version": 1, "entries": incoming},
                                source_blob_sha="new-blob", source_commit="new-commit",
                                snapshot_date="2026-11-07")
        after = {x["dzen_id"]: x for x in merged["entries"]}
        self.assertEqual(after[ident]["title"], old["entries"][0]["title"])
        self.assertEqual(len(after), len(old["entries"]))

    def test_add_new_proven_link_but_reject_unproven_one(self):
        old = copy.deepcopy(self.snapshot)
        incoming = copy.deepcopy(old["entries"][:150])
        fresh = copy.deepcopy(incoming[0])
        fresh["dzen_id"] = "eeeeeeeeeeeeeeeeeeeeeeee"
        fresh["dzen_url"] = canonical_dzen_url(fresh["dzen_id"])
        fresh["title"] = "Подтверждённая тестовая ссылка"
        incoming.append(fresh)
        fake = dict(fresh, dzen_id="ffffffffffffffffffffffff",
                    dzen_url=canonical_dzen_url("ffffffffffffffffffffffff"),
                    url_evidence="derived_from_12_byte_id")
        incoming.append(fake)
        merged = merge_snapshot(old, {"schema_version": 1, "entries": incoming},
                                source_blob_sha="new-blob", source_commit="new-commit",
                                snapshot_date="2026-11-07")
        after = {x["dzen_id"]: x for x in merged["entries"]}
        self.assertEqual(len(after), len(old["entries"]) + 1)
        self.assertIn(fresh["dzen_id"], after)
        self.assertNotIn(fake["dzen_id"], after)

    def test_duplicate_upstream_id_is_rejected(self):
        old = self.snapshot
        incoming = copy.deepcopy(old["entries"][:150])
        incoming.append(copy.deepcopy(incoming[0]))
        with self.assertRaisesRegex(ValueError, "Duplicate ID"):
            merge_snapshot(old, {"schema_version": 1, "entries": incoming},
                           source_blob_sha="sha", source_commit="commit",
                           snapshot_date="2026-11-07")

    def test_git_blob_hash(self):
        self.assertEqual(blob_sha(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")


if __name__ == "__main__":
    unittest.main()
