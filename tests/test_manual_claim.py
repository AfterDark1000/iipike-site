import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import manual_claim, site_news_pool, editorial_routing

NOW = "2026-11-26T09:00:00+00:00"
LATER = "2026-11-26T10:00:00+00:00"


class ManualClaimTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        base = {"schema_version": 1, "note": "fixture only", "items": []}
        records = [{"title": "Fixture story number " + str(n),
                    "source_url": "https://example.org/story-" + str(n),
                    "priority": "high" if n in (3, 4, 5) else "normal"}
                   for n in range(1, 8)]
        pool, _ = site_news_pool.add(base, records, now=NOW)
        pool["items"][4].update(status="in_review", review_started_at=NOW)
        self.pool = pool
        self.routes = {"schema_version": 1, "approved_date": "2026-11-26",
                       "source": "fixture", "source_pool_sha": "fixture",
                       "note": "fixture", "items": []}
        for n, lane, decision in ((2, "long", "hot"), (3, "short", "short"),
                                  (4, "hold", "defer"), (6, "long", "hot")):
            self.routes["items"].append({"sequence": n,
                "pool_id": pool["items"][n - 1]["id"],
                "lane": lane, "decision": decision})
        manual_claim.dump(self.root / manual_claim.POOL, self.pool)
        manual_claim.dump(self.root / editorial_routing.ROUTES, self.routes)

    def request(self, name, body=None):
        path = self.root / manual_claim.REQUESTS / (name + ".json")
        manual_claim.dump(path, manual_claim.BODY if body is None else body)
        return path.name

    def read_pool(self):
        return json.loads((self.root / manual_claim.POOL).read_text())

    def test_hot_fifo_then_ordinary_and_idempotence(self):
        a = self.request("manual-op-000001")
        b = self.request("manual-op-000002")
        c = self.request("manual-op-000003")
        outcomes = manual_claim.consume(self.root, now=LATER)
        self.assertEqual([outcomes[n]["pool_sequence"] for n in (a,b,c)], [2,6,1])
        self.assertEqual([outcomes[n]["effective_priority"] for n in (a,b,c)],
                         ["high","high","normal"])
        changed = self.read_pool()
        expected = copy.deepcopy(self.pool)
        for index in (0,1,5):
            expected["items"][index].update(status="in_review", review_started_at=LATER)
        self.assertEqual(changed, expected)
        self.assertEqual(manual_claim.consume(self.root, now=LATER), {})
        self.assertEqual(self.read_pool(), expected)
        self.assertEqual(json.loads((self.root / editorial_routing.ROUTES).read_text()),
                         self.routes)

    def test_route_changed_before_claim_is_used(self):
        self.routes["items"][0].update(lane="hold", decision="defer")
        manual_claim.dump(self.root / editorial_routing.ROUTES, self.routes)
        a = self.request("manual-op-000001")
        self.assertEqual(manual_claim.consume(self.root, now=LATER)[a]["pool_sequence"],6)

    def test_rejects_modified_request_and_invalid_worker(self):
        a = self.request("manual-op-000001", {**manual_claim.BODY, "worker":"other"})
        result = manual_claim.consume(self.root, now=LATER)
        self.assertEqual(result[a]["status"], "rejected")
        self.assertEqual(self.read_pool(), self.pool)
        self.request("manual-op-000001")
        with self.assertRaises(ValueError):
            manual_claim.consume(self.root, now=LATER)
        self.assertEqual(self.read_pool(), self.pool)

    def test_no_long_news_and_existing_review_unchanged(self):
        for n in (0,1,5,6):
            self.pool["items"][n].update(status="in_review", review_started_at=NOW)
        manual_claim.dump(self.root / manual_claim.POOL, self.pool)
        a = self.request("manual-op-000001")
        self.assertEqual(manual_claim.consume(self.root, now=LATER)[a]["status"],"no_long_news")
        self.assertEqual(self.read_pool(),self.pool)

    def test_bad_routing_fails_closed(self):
        self.routes["items"][0]["pool_id"] = "n-0000000000000000"
        manual_claim.dump(self.root / editorial_routing.ROUTES,self.routes)
        self.request("manual-op-000001")
        with self.assertRaises(ValueError):
            manual_claim.consume(self.root,now=LATER)
        self.assertEqual(self.read_pool(),self.pool)

    def test_checkpoint_and_return_keep_receipt_idempotent(self):
        a = self.request("manual-op-000001")
        claim = manual_claim.consume(self.root, now=LATER)[a]
        pool = self.read_pool()
        pool, _ = site_news_pool.checkpoint(pool, claim["pool_id"], "fixture checkpoint")
        pool, _ = site_news_pool.transition(pool, claim["pool_id"], "return")
        manual_claim.dump(self.root / manual_claim.POOL, pool)
        self.assertEqual(manual_claim.consume(self.root, now=LATER), {})
        self.assertEqual(self.read_pool(),pool)

    def test_probe_never_reserves(self):
        a = self.request("manual-probe-000001", {**manual_claim.BODY, "action":"probe"})
        rec = manual_claim.consume(self.root, now=LATER)[a]
        self.assertEqual(rec["status"], "probe_ok")
        self.assertTrue(rec["pool_unchanged"])
        self.assertEqual(self.read_pool(), self.pool)

    def test_bound_checkpoint_return_and_stale_rejection(self):
        a = self.request("manual-op-000001")
        claim = manual_claim.consume(self.root, now=LATER)[a]
        body = {**manual_claim.BODY, "action":"checkpoint", "claim_request":a,
                **{k:claim[k] for k in ("pool_id","pool_sequence","claimed_at")},
                "expected_note":"", "note":"Verified primary source"}
        b = self.request("manual-op-000002",body)
        self.assertEqual(manual_claim.consume(self.root,now=LATER)[b]["status"], "checkpointed")
        c = self.request("manual-op-000003",body)
        self.assertEqual(manual_claim.consume(self.root,now=LATER)[c]["status"], "rejected")
        d = self.request("manual-op-000004",{**body,"action":"return","human_authorized":True,
                             "expected_note":body["note"],"note":"Human requested return"})
        self.assertEqual(manual_claim.consume(self.root,now=LATER)[d]["status"], "returned")
        self.assertEqual(self.read_pool()["items"][1]["status"],"queued")

    def test_reject_foreign_claim_and_approval_without_story(self):
        a = self.request("manual-op-000001")
        claim = manual_claim.consume(self.root, now=LATER)[a]
        body = {**manual_claim.BODY,"action":"approve","claim_request":a,
                **{k:claim[k] for k in ("pool_id","pool_sequence","claimed_at")},
                "expected_note":"", "note":"Human approved", "human_authorized":True,
                "article_id":"fixture-story", "story_sha":"a"*40}
        b = self.request("manual-op-000002",body)
        self.assertEqual(manual_claim.consume(self.root,now=LATER)[b]["status"],"rejected")
        c = self.request("manual-op-000003",{**{k:v for k,v in body.items() if k not in {"article_id","story_sha","human_authorized"}}, "action":"reject","claim_request":"manual-fake-000001.json", "note":"Wrong claim"})
        self.assertEqual(manual_claim.consume(self.root,now=LATER)[c]["status"],"rejected")
        self.assertEqual(self.read_pool()["items"][1]["status"],"in_review")


    def collection_fixture(self, registered=True):
        # Primary #2 is already a long-lane hot fixture; turn it into a
        # verified ready collection, with two held, unreserved secondaries.
        self.pool["items"][1]["priority"] = "normal"
        members = []
        for n in (2, 3, 4):
            item = self.pool["items"][n-1]
            item["priority"] = "normal"
            route = next(r for r in self.routes["items"] if r["sequence"] == n)
            route.update(lane="long" if n == 2 else "hold",
                         decision="linked_primary" if n == 2 else "linked_secondary",
                         group="fixture_collection", group_primary=2)
            members.append({"sequence": n, "pool_id": item["id"]})
        # Keep #2 first in ordinary FIFO rather than unrelated hot #6.
        self.pool["items"][0].update(status="in_review", review_started_at=NOW)
        self.pool["items"][5].update(status="in_review", review_started_at=NOW)
        manual_claim.dump(self.root / manual_claim.POOL, self.pool)
        manual_claim.dump(self.root / editorial_routing.ROUTES, self.routes)
        if registered:
            from scripts import editorial_collections
            manual_claim.dump(self.root / editorial_collections.PATH, {
                "schema_version": 1, "items": [{"group": "fixture_collection",
                "title": "Fixture collection", "state": "ready_for_editor",
                "primary_sequence": 2, "members": members, "note": "Fixture only"}]})
        name = self.request("manual-group-000001")
        claim = manual_claim.consume(self.root, now=LATER)[name]
        self.assertEqual(claim["pool_sequence"], 2)
        return {**manual_claim.BODY, "action": "approve", "claim_request": name,
                **{k:claim[k] for k in ("pool_id","pool_sequence","claimed_at")},
                "expected_note": "", "note": "Human approved full collection",
                "human_authorized": True, "article_id": "fixture-collection", "story_sha": "a"*40}

    def test_approve_ready_collection_closes_all_members_atomically(self):
        from unittest.mock import patch
        body = self.collection_fixture()
        name = self.request("manual-group-000002", body)
        with patch("scripts.manual_claim.approved_story"):
            result = manual_claim.consume(self.root, now=LATER)[name]
        self.assertEqual(result["status"], "closed_approved")
        self.assertEqual([m["pool_sequence"] for m in result["merged_members"]], [3,4])
        after = self.read_pool()
        for n in (2,3,4):
            self.assertEqual(after["items"][n-1]["status"], "approved")
            self.assertEqual(after["items"][n-1]["article_id"], "fixture-collection")
        self.assertIn("Объединено с №2", after["items"][2]["note"])
        self.assertEqual(after["items"][4], self.pool["items"][4])
        self.assertEqual(manual_claim.consume(self.root, now=LATER), {})

    def test_approve_collection_conflicting_member_does_not_close_primary(self):
        from unittest.mock import patch
        body = self.collection_fixture()
        before = self.read_pool()
        before["items"][3].update(status="in_review", review_started_at=NOW)
        manual_claim.dump(self.root / manual_claim.POOL, before)
        name = self.request("manual-group-000002", body)
        with patch("scripts.manual_claim.approved_story"):
            result = manual_claim.consume(self.root, now=LATER)[name]
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(self.read_pool(), before)

    def test_legacy_group_requires_explicit_members_and_preserves_other_candidate(self):
        from unittest.mock import patch
        body = self.collection_fixture(registered=False)
        before = self.read_pool()
        a = self.request("manual-group-000002", body)
        b = self.request("manual-group-000003", {**body, "included_pool_ids": [self.pool["items"][2]["id"]]})
        with patch("scripts.manual_claim.approved_story"):
            result = manual_claim.consume(self.root, now=LATER)
        self.assertEqual(result[a]["status"], "rejected")
        self.assertEqual(result[b]["status"], "closed_approved")
        self.assertEqual(self.read_pool()["items"][3], before["items"][3])


if __name__ == "__main__":
    unittest.main()
