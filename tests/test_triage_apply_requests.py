"""Prove immutable approved triage requests never steal in-review items."""
import copy
import json
import tempfile
from pathlib import Path
import unittest
from scripts.site_news_pool import add, validate as validate_pool
from scripts import editorial_routing, triage_apply_requests as t

NOW = "2026-11-19T06:00:00+00:00"


def fixture():
    original = {"schema_version": 1, "note": "Tests only", "items": []}
    pool, _ = add(original, [
        {"title": "First long news", "source_url": "https://example.org/a"},
        {"title": "Second long news", "source_url": "https://example.org/b"},
        {"title": "Third long news", "source_url": "https://example.org/c"},
    ], now=NOW)
    doc = {
        "schema_version": 1, "approved_date": "2026-11-19",
        "source": "test", "source_pool_sha": "test", "note": "Fixture",
        "items": [
            {"pool_id": x["id"], "sequence": x["sequence"],
             "decision": "full", "lane": "long"} for x in pool["items"]
        ]
    }
    return pool, doc


def row(item, decision, *, priority=None):
    lane = t.DECISION_LANE[decision]
    res = {"pool_id": item["id"], "sequence": item["sequence"],
           "lane": lane, "decision": decision}
    if priority is not None:
        res["priority"] = priority
    return res


def request(items):
    return {"schema_version": 1, "action": "apply_approved_triage",
            "worker": "hpii-morning-triage",
            "approval": "explicit_chief_editor_chat_command",
            "items": items}


class TriageRequestTests(unittest.TestCase):
    def test_apply_route_and_priority_without_changing_identity_or_status(self):
        pool, routes = fixture()
        before = copy.deepcopy(pool)
        newpool, newroutes, out = t.apply_request(pool, routes, request([
            row(pool["items"][0], "short"),
            row(pool["items"][1], "hot"),
            row(pool["items"][2], "defer", priority="low"),
        ]), source="test-request.json")
        self.assertEqual(out["applied"], [1, 2, 3])
        self.assertEqual([x["priority"] for x in newpool["items"]],
                         ["normal", "high", "low"])
        self.assertTrue(all(x["status"] == "queued" for x in newpool["items"]))
        self.assertEqual([x["id"] for x in before["items"]],
                         [x["id"] for x in newpool["items"]])
        self.assertEqual([x["lane"] for x in newroutes["items"]],
                         ["short", "long", "hold"])
        validate_pool(newpool)

    def test_busy_and_closed_entries_not_overwritten(self):
        pool, routes = fixture()
        pool["items"][0].update(status="in_review", review_started_at=NOW)
        pool["items"][1].update(status="rejected", closed_at=NOW)
        unchanged_busy = copy.deepcopy(pool["items"][:2])
        result, updated_routes, out = t.apply_request(pool, routes, request([
            row(pool["items"][0], "short"),
            row(pool["items"][1], "hot"),
            row(pool["items"][2], "short"),
        ]), source="test.json")
        self.assertEqual(out["applied"], [3])
        self.assertEqual(len(out["skipped"]), 2)
        self.assertEqual(result["items"][:2], unchanged_busy)
        self.assertEqual([i["lane"] for i in updated_routes["items"]],
                         ["long", "long", "short"])

    def test_persist_receipt_and_replay_safe(self):
        pool, route = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, payload in ((t.POOL, pool), (t.ROUTES, route)):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            path = root / t.REQUESTS / "20261119-approval-001.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(request([
                row(pool["items"][0], "short"), row(pool["items"][2], "hot")
            ])), encoding="utf-8")
            first = t.consume(root)
            self.assertEqual(first[path.name]["status"], "applied")
            self.assertEqual(first[path.name]["applied"], [1, 3])
            saved = json.loads((root / t.POOL).read_text())
            self.assertEqual(saved["items"][2]["priority"], "high")
            self.assertEqual(t.consume(root), {})
            self.assertEqual(saved, json.loads((root / t.POOL).read_text()))
            path.write_text('{"modified":true}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed after applying"):
                t.consume(root)

    def test_reject_bad_approval_duplicate_and_impossible_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test-approval.json"
            pool, _ = fixture()
            bad = request([row(pool["items"][0], "short")])
            bad["approval"] = "inferred"
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "approval"):
                t.read_request(path)
            bad = request([row(pool["items"][0], "short")] * 2)
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                t.read_request(path)
            bad = request([row(pool["items"][0], "short", priority="high")])
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "priority"):
                t.read_request(path)

    def test_wrong_id_skipped_without_replacing_route(self):
        pool, routes = fixture()
        bad = request([{"pool_id": "n-1234567890abcdef",
                        "sequence": pool["items"][0]["sequence"],
                        "lane": "short", "decision": "short"}])
        changed, routed, result = t.apply_request(pool, routes, bad, source="test.json")
        self.assertEqual(result["skipped"][0]["reason"], "missing_or_changed_id")
        self.assertEqual(pool, changed)
        self.assertEqual(routes, routed)


if __name__ == "__main__":
    unittest.main()
