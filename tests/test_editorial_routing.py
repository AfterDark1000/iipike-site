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

    def test_hot_routed_priority_takes_precedence_over_raw_normal(self):
        pool, routes = fixture()
        pool["items"][2]["priority"] = "normal"
        manual, selected = next_item(pool, now=NOW, routing=routes)
        self.assertEqual(selected["sequence"], 3)
        self.assertEqual(manual["items"][2]["status"], "in_review")
        # The ordinary-only automatic editor must also respect the hot routing.
        _, ticket = claim_ordinary(pool, "test-routed-hot.json", now=NOW, routing=routes)
        self.assertEqual(ticket["pool_sequence"], 4)

    def test_request_receipt_claim_is_idempotent(self):
        from scripts import briefs_claim
        import json
        from scripts.editorial_routing import ROUTES
        pool, routes = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "data/site_news_pool.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
            route_file = root / ROUTES
            route_file.parent.mkdir(parents=True, exist_ok=True)
            doc = {
                "schema_version": 1, "approved_date": "2026-11-19",
                "source": "test", "source_pool_sha": "test", "note": "test",
                "items": list(routes.values())
            }
            route_file.write_text(json.dumps(doc), encoding="utf-8")
            requests = root / briefs_claim.REQUESTS
            requests.mkdir(parents=True)
            req = requests / "test-short-001.json"
            req.write_text(json.dumps({
                "schema_version": 1, "action": "claim_short", "worker": "hpii-short-editor"
            }), encoding="utf-8")
            first = briefs_claim.consume(root, now=NOW)
            self.assertEqual(first[req.name]["pool_sequence"], 1)
            self.assertEqual(first[req.name]["status"], "reserved")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["items"][0]["status"], "in_review")
            self.assertEqual(briefs_claim.consume(root, now=NOW), {})
            self.assertEqual(saved, json.loads(path.read_text(encoding="utf-8")))
            another = requests / "test-short-002.json"
            another.write_text(req.read_text(encoding="utf-8"), encoding="utf-8")
            blocked = briefs_claim.consume(root, now=NOW)
            self.assertEqual(blocked[another.name]["status"], "short_work_in_progress")
            self.assertEqual(saved, json.loads(path.read_text(encoding="utf-8")))
            req.write_text('{"worker":"evil"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed after acknowledgment"):
                briefs_claim.consume(root, now=NOW)

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

    def test_claim_up_to_five_short_items_atomically(self):
        from scripts.editorial_routing import claim_short_batch
        pool = {"schema_version": 1, "note": "Testing batch", "items": []}
        records = [
            {"title": "Batch short news number " + str(i),
             "source_url": "https://example.org/short/" + str(i)}
            for i in range(1, 8)
        ]
        pool, _ = add(pool, records, now=NOW)
        routes = {
            x["id"]: {"pool_id": x["id"], "sequence": x["sequence"],
                       "lane": "short" if x["sequence"] < 7 else "long",
                       "decision": "short" if x["sequence"] < 7 else "full"}
            for x in pool["items"]
        }
        with tempfile.TemporaryDirectory() as tmp:
            updated, rows = claim_short_batch(
                pool, count=5, now=NOW, root=Path(tmp), routes=routes)
            self.assertEqual([x["sequence"] for x in rows], [1, 2, 3, 4, 5])
            self.assertEqual(sum(x["status"] == "in_review" for x in updated["items"]), 5)
            self.assertEqual(updated["items"][5]["status"], "queued")
            self.assertEqual(updated["items"][6]["status"], "queued")
            self.assertEqual(claim_short_batch(
                updated, count=5, now=NOW, root=Path(tmp), routes=routes)[1], [])
            with self.assertRaisesRegex(ValueError, "1..5"):
                claim_short_batch(pool, count=6, routes=routes, root=Path(tmp))

    def test_batch_request_receipt_contains_all_confirmed_ids(self):
        from scripts import briefs_claim
        from scripts.editorial_routing import ROUTES
        import json
        pool = {"schema_version": 1, "note": "Batch request test", "items": []}
        pool, _ = add(pool, [
            {"title": f"Short briefing article {i}",
             "source_url": f"https://example.org/brief/{i}"}
            for i in range(1, 7)
        ], now=NOW)
        route = {
            "schema_version": 1, "approved_date": "2026-11-19",
            "source": "fixture", "source_pool_sha": "fixture", "note": "fixture",
            "items": [{"pool_id": x["id"], "sequence": x["sequence"],
                        "lane": "short", "decision": "short"} for x in pool["items"]]
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path, data in (("data/site_news_pool.json", pool), (str(ROUTES), route)):
                dest = root / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            req = root / briefs_claim.REQUESTS / "batch-short-001.json"
            req.parent.mkdir(parents=True, exist_ok=True)
            req.write_text(json.dumps({"schema_version": 1,
                "action": "claim_short", "worker": "hpii-short-editor", "count": 5}))
            first = briefs_claim.consume(root, now=NOW)[req.name]
            self.assertEqual(first["status"], "reserved")
            self.assertEqual(first["count"], 5)
            self.assertEqual([x["pool_sequence"] for x in first["items"]], [1,2,3,4,5])
            self.assertEqual(briefs_claim.consume(root, now=NOW), {})
            request2 = req.parent / "batch-short-002.json"
            request2.write_text(req.read_text())
            blocked = briefs_claim.consume(root, now=NOW)[request2.name]
            self.assertEqual(blocked["status"], "short_work_in_progress")

    def test_editor_can_start_next_batch_after_chat_approval_before_publication(self):
        from scripts.editorial_routing import short_work_in_progress, claim_short_batch
        import json
        import shutil
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("data/briefs/candidates.json", "data/briefs/approved.json", "news.json"):
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(repo / name, dest)
            approved = json.loads((root / "data/briefs/approved.json").read_text())["items"]
            one = next(r for r in approved if r["pool_sequence"] == 59)
            pool = {"schema_version":1, "note":"Test approved WIP", "items":[]}
            pool, _ = add(pool, [
                {"title":"Already approved short story", "source_url":"https://example.org/a"},
                {"title":"Next eligible short story", "source_url":"https://example.org/b"},
            ], now=NOW)
            existing = pool["items"][0]
            existing["id"] = one["pool_id"]
            existing["status"] = "in_review"
            existing["review_started_at"] = NOW
            existing["note"] = "SHORT_EDITOR claim=short; pool_id=" + existing["id"]
            # The next new item still has an ordinary, unique pool ID.
            validate_pool(pool)
            routes = {i["id"]: {
                "pool_id":i["id"],"sequence":i["sequence"],"lane":"short","decision":"short"}
                for i in pool["items"]}
            self.assertFalse(short_work_in_progress(pool, root=root))
            next_pool, claimed = claim_short_batch(
                pool, count=1, root=root, now=NOW, routes=routes)
            self.assertEqual(len(claimed),1)
            self.assertEqual(claimed[0]["sequence"],2)
            self.assertEqual(next_pool["items"][0]["status"], "in_review")

    def test_unrouted_future_news_defaults_to_long(self):
        pool, routes = fixture()
        self.assertTrue(long_allowed({"id": "n-0000000000000000"}, routes))



    def test_return_short_to_ordinary_request(self):
        import json
        from scripts import briefs_claim
        pool, routes = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pool, item = claim_short(pool, routes=routes, root=root, now=NOW)
            route_doc = {"schema_version": 1, "approved_date": "2026-11-19",
                         "source": "test", "source_pool_sha": "test", "note": "test",
                         "items": list(routes.values())}
            candidate = {"status": "pending_review", "pool_id": item["id"],
                         "slug": "short-test", "headline": "Short test",
                         "body": "Draft", "fact_check": "test", "source_url": item["source_url"]}
            for path, obj in ((briefs_claim.POOL, pool),
                              (Path("data/editorial_routing.json"), route_doc),
                              (Path("data/briefs/candidates.json"), {"schema_version": 1, "items": [candidate]})):
                dest = root / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(json.dumps(obj), encoding="utf-8")
            req = root / briefs_claim.REQUESTS / "return-short-001.json"
            req.parent.mkdir(parents=True)
            req.write_text(json.dumps({"schema_version": 1, "action": "return_to_long",
                "worker": "hpii-short-editor", "pool_id": item["id"],
                "pool_sequence": item["sequence"], "claimed_at": NOW}))
            receipt = briefs_claim.consume(root, now=NOW)[req.name]
            self.assertEqual(receipt["status"], "returned_to_long")
            self.assertEqual(receipt["removed_candidate"], "short-test")
            saved = json.loads((root / briefs_claim.POOL).read_text())
            target = saved["items"][0]
            self.assertEqual((target["status"], target["priority"], target["review_started_at"]),
                             ("queued", "normal", None))
            self.assertEqual(saved["items"][1:], pool["items"][1:])
            route_saved = json.loads((root / "data/editorial_routing.json").read_text())
            self.assertEqual(route_saved["items"][0]["decision"], "full")
            self.assertEqual(route_saved["items"][1:], route_doc["items"][1:])
            self.assertEqual(json.loads((root / "data/briefs/candidates.json").read_text())["items"], [])
            self.assertEqual(briefs_claim.consume(root, now=NOW), {})

    def test_return_rejects_approved_foreign_and_stale(self):
        from scripts.briefs_claim import return_to_long
        pool, routes = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            pool, item = claim_short(pool, routes=routes, root=Path(tmp), now=NOW)
        route_doc = {"schema_version": 1, "approved_date": "2026-11-19",
                     "source": "test", "source_pool_sha": "test", "note": "test",
                     "items": list(routes.values())}
        req = {"pool_id": item["id"], "pool_sequence": item["sequence"], "claimed_at": NOW}
        original = copy.deepcopy(pool)
        with self.assertRaisesRegex(ValueError, "Approved"):
            return_to_long(pool, route_doc, {"items": []},
                           {"items": [{"pool_id": item["id"]}]}, req)
        with self.assertRaisesRegex(ValueError, "stale"):
            return_to_long(pool, route_doc, {"items": []}, {"items": []},
                           {**req, "claimed_at": "2026-11-20T05:00:00+00:00"})
        with self.assertRaisesRegex(ValueError, "stale"):
            return_to_long(pool, route_doc, {"items": []}, {"items": []},
                           {**req, "pool_sequence": 99})
        foreign = copy.deepcopy(pool)
        foreign["items"][0]["note"] = "Other editor"
        with self.assertRaisesRegex(ValueError, "another worker"):
            return_to_long(foreign, route_doc, {"items": []}, {"items": []}, req)
        self.assertEqual(pool, original)


if __name__ == "__main__":
    unittest.main()
