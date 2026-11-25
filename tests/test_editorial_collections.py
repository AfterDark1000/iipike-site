"""Tests for editorial collection accumulation, guarding and chief-editor release."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.site_news_pool import add, next_item
from scripts.auto_editor_workbench import claim_ordinary
from scripts import editorial_collections as c, editorial_routing as routing
from scripts import triage_apply_requests as triage

NOW = "2026-11-25T03:00:00+00:00"
GROUP = "experimental_small_ai_projects"


def fixture():
    pool, _ = add({"schema_version": 1, "note": "Collection fixture.", "items": []}, [
        {"title": "Story about a small experimental game", "source_url": "https://example.org/1"},
        {"title": "Story about another artistic experiment", "source_url": "https://example.org/2"},
        {"title": "Story about a visual world", "source_url": "https://example.org/3"},
        {"title": "Story about independent breakthrough", "source_url": "https://example.org/4"},
        {"title": "Story about a fifth standalone item", "source_url": "https://example.org/5"},
    ], now=NOW)
    routes = {"schema_version": 1, "approved_date": "2026-11-25",
              "source": "test", "source_pool_sha": "test", "note": "test",
              "items": [{"sequence": x["sequence"], "pool_id": x["id"],
                         "lane": "long", "decision": "full"} for x in pool["items"]]}
    return pool, routes, c.empty()


def members(pool, seqs):
    return [{"sequence": seq, "pool_id": pool["items"][seq - 1]["id"]}
            for seq in seqs]


def collection(pool, seqs=(1, 2, 3), *, state="collecting"):
    return {"group": GROUP, "title": "Interesting small AI-generated projects",
            "note": "Collect genuinely different and checked demonstrations.",
            "state": state, "primary_sequence": 1,
            "members": members(pool, seqs)}


def request(value):
    return {"schema_version": 1, "action": "collection_upsert",
            "worker": "hpii-morning-triage",
            "approval": "explicit_chief_editor_chat_command",
            "collection": value}


class CollectionTests(unittest.TestCase):
    def test_collecting_blocks_manual_and_auto_claims(self):
        pool, routes, cols = fixture()
        original = copy.deepcopy(pool)
        p, r, coll, receipt = c.apply_request(
            pool, routes, cols, request(collection(pool)), source="test.json")
        self.assertEqual(receipt["applied"], [1, 2, 3])
        self.assertEqual(pool, original)
        self.assertEqual(coll["items"][0]["state"], "collecting")
        self.assertEqual({x["sequence"]: x["decision"] for x in r["items"]},
                         {1: "defer", 2: "linked_secondary", 3: "linked_secondary",
                          4: "full", 5: "full"})
        mapped = {x["pool_id"]: x for x in r["items"]}
        self.assertFalse(routing.long_allowed(p["items"][0], mapped))
        _, manual = next_item(p, now=NOW, routing=mapped)
        self.assertEqual(manual["sequence"], 4)
        _, auto = claim_ordinary(p, "test-collection-01.json",
                                 now=NOW, routing=mapped)
        self.assertEqual(auto["pool_sequence"], 4)
        self.assertTrue(all(i["status"] == "queued" for i in p["items"]))
        c.validate_document(coll, p, r)

    def test_ready_opens_leader_and_preserves_companions(self):
        pool, routes, cols = fixture()
        p, r, coll, _ = c.apply_request(
            pool, routes, cols, request(collection(pool)), source="create")
        p, r, coll, receipt = c.apply_request(
            p, r, coll, request(collection(pool, state="ready_for_editor")),
            source="chief-release")
        self.assertEqual(receipt["applied"], [1, 2, 3])
        m = {x["pool_id"]: x for x in r["items"]}
        _, chosen = next_item(p, now=NOW, routing=m)
        self.assertEqual(chosen["sequence"], 1)
        _, automated = claim_ordinary(p, "test-collection-02.json",
                                      now=NOW, routing=m)
        self.assertEqual(automated["pool_sequence"], 4)
        self.assertFalse(routing.long_allowed(p["items"][1], m))
        c.validate_document(coll, p, r)

    def test_incremental_append_is_not_fixed_to_four(self):
        pool, routes, cols = fixture()
        p, r, coll, _ = c.apply_request(
            pool, routes, cols, request(collection(pool, (1, 2))), source="create")
        self.assertEqual(len(coll["items"][0]["members"]), 2)
        p, r, coll, _ = c.apply_request(
            p, r, coll, request(collection(pool, (1, 2, 3, 4))), source="append")
        self.assertEqual(len(coll["items"][0]["members"]), 4)
        m = {x["pool_id"]: x for x in r["items"]}
        _, manual = next_item(p, now=NOW, routing=m)
        self.assertEqual(manual["sequence"], 5)

    def test_reject_reserved_item_and_bad_id_without_changes(self):
        pool, routes, cols = fixture()
        pool["items"][1].update(status="in_review", review_started_at=NOW)
        with self.assertRaisesRegex(ValueError, "reserved"):
            c.apply_request(pool, routes, cols, request(collection(pool)),
                            source="conflict")
        self.assertEqual(routes["items"][0]["decision"], "full")
        pool["items"][1].update(status="queued", review_started_at=None)
        wrong = collection(pool)
        wrong["members"][0]["pool_id"] = "n-0000000000000000"
        with self.assertRaisesRegex(ValueError, "unknown"):
            c.apply_request(pool, routes, cols, request(wrong), source="conflict")

    def test_cannot_silently_remove_members(self):
        pool, routes, cols = fixture()
        p, r, coll, _ = c.apply_request(
            pool, routes, cols, request(collection(pool)), source="create")
        with self.assertRaisesRegex(ValueError, "release"):
            c.apply_request(p, r, coll,
                            request(collection(pool, (1, 2))), source="shrink")

    def test_release_individual_breakthrough_for_full_or_hot(self):
        pool, routes, cols = fixture()
        p, r, coll, _ = c.apply_request(
            pool, routes, cols, request(collection(pool)), source="create")
        release = {"schema_version": 1, "action": "collection_release_member",
                   "worker": "hpii-morning-triage",
                   "approval": "explicit_chief_editor_chat_command",
                   "group": GROUP, "member": members(pool, (3,))[0],
                   "decision": "hot"}
        p, r, coll, outcome = c.apply_request(p, r, coll, release, source="release")
        self.assertEqual(outcome["applied"], [3])
        self.assertEqual(p["items"][2]["priority"], "high")
        self.assertEqual([m["sequence"] for m in coll["items"][0]["members"]],
                         [1, 2])
        self.assertEqual(r["items"][2]["decision"], "hot")
        c.validate_document(coll, p, r)

    def test_reject_primary_release(self):
        pool, routes, cols = fixture()
        p, r, coll, _ = c.apply_request(
            pool, routes, cols, request(collection(pool)), source="create")
        release = {"schema_version": 1, "action": "collection_release_member",
                   "worker": "hpii-morning-triage",
                   "approval": "explicit_chief_editor_chat_command",
                   "group": GROUP, "member": members(pool, (1,))[0],
                   "decision": "full"}
        with self.assertRaisesRegex(ValueError, "primary"):
            c.apply_request(p, r, coll, release, source="release")

    def test_reject_unauthorized_stage_transition(self):
        pool, routes, cols = fixture()
        bad = request(collection(pool))
        bad["approval"] = "model_approval"
        with self.assertRaisesRegex(ValueError, "approval"):
            c.validate_request(bad)
        bad = request(collection(pool))
        bad["collection"]["members"][1]["pool_id"] = bad["collection"]["members"][0]["pool_id"]
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            c.validate_request(bad)

    def test_registry_catches_route_drift(self):
        pool, routes, cols = fixture()
        p, r, coll, _ = c.apply_request(
            pool, routes, cols, request(collection(pool)), source="create")
        r["items"][0]["decision"] = "linked_primary"
        r["items"][0]["lane"] = "long"
        with self.assertRaisesRegex(ValueError, "state"):
            c.validate_document(coll, p, r)

    def test_consumer_receipt_is_idempotent_and_old_triage_cannot_override(self):
        pool, routes, cols = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, data in ((triage.POOL, pool), (triage.ROUTES, routes),
                              (c.PATH, cols)):
                dest = root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(json.dumps(data), encoding="utf-8")
            reqdir = root / triage.REQUESTS
            reqdir.mkdir(parents=True, exist_ok=True)
            req1 = reqdir / "collection-a-001.json"
            req1.write_text(json.dumps(request(collection(pool))), encoding="utf-8")
            first = triage.consume(root)[req1.name]
            self.assertEqual(first["status"], "applied")
            self.assertEqual(first["applied"], [1, 2, 3])
            self.assertEqual(triage.consume(root), {})
            locked = json.loads((root / triage.ROUTES).read_text())
            self.assertEqual(locked["items"][0]["lane"], "hold")
            # A regular triage update bypassing the registry is rejected atomically.
            req2 = reqdir / "collection-b-001.json"
            req2.write_text(json.dumps({
                "schema_version": 1, "action": "apply_approved_triage",
                "worker": "hpii-morning-triage",
                "approval": "explicit_chief_editor_chat_command",
                "items": [{"sequence": 1, "pool_id": pool["items"][0]["id"],
                           "lane": "long", "decision": "full"}]}), encoding="utf-8")
            second = triage.consume(root)[req2.name]
            self.assertEqual(second["status"], "rejected")
            self.assertEqual(locked, json.loads((root / triage.ROUTES).read_text()))
            self.assertEqual(json.loads((root / c.PATH).read_text())["items"][0]["state"],
                             "collecting")


if __name__ == "__main__":
    unittest.main()
