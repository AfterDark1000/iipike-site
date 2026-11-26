import datetime as dt
import unittest
from scripts.auto_editor_dispatch import select
from scripts.auto_editor_workbench import claim_ordinary, draft_template
from test_auto_editor_workbench import pool_with

NOW=dt.datetime(2026,11,26,18,tzinfo=dt.timezone.utc)
class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.pool=pool_with(("Hot human story","high"),("Unsorted ordinary story","normal"),("Full ordinary story","normal"),("Next ordinary story","normal"))
        self.routes={x["id"]:{"lane":"long","decision":"full"} for x in self.pool["items"][2:]}
    def choose(self,receipts=None,drafts=None,decisions=None,flags=None,requests=None):
        return select(self.pool,self.routes,receipts or {},drafts or {},decisions or {},flags or [],requests or [],set(),NOW)
    def reserve(self):
        self.pool,r=claim_ordinary(self.pool,"request-fixture.json",now=NOW.isoformat(),routing=self.routes,strict_routes=True)
        return {"request-fixture.json":{"schema_version":1,"request":"request-fixture.json","status":"reserved",**r}}
    def test_preview_no_write_hot_and_unsorted_excluded(self):
        state,job,counts=self.choose()
        self.assertEqual((state,job["kind"],job["candidate"]["sequence"]),("ready","new",3))
        self.assertTrue(all(x["status"]=="queued" for x in self.pool["items"]))
    def test_pending_request_is_not_duplicated(self):
        self.assertEqual(self.choose(requests=["request-old.json"])[1],{"kind":"await_receipt","request":"request-old.json"})
    def test_missing_draft_resumes_own_receipt(self):
        rec=self.reserve()
        self.assertEqual(self.choose(receipts=rec)[1]["kind"],"resume")
    def test_human_revision_before_new_request(self):
        rec=self.reserve();r=next(iter(rec.values()));d=draft_template(r)
        ident=r["article_id"]
        decision={"action":"revise","revision":1,"updated_at":d["updated_at"],"draft_blob_sha":"a"*40,"decided_at":NOW.isoformat(),"note":"Fix headline"}
        self.assertEqual(self.choose(rec,{ident:(d,"a"*40)},{ident+"-r1.json":(decision,"b"*40)})[1]["kind"],"revise")
    def test_rejected_draft_is_not_resumed(self):
        rec=self.reserve();r=next(iter(rec.values()));d=draft_template(r);ident=r["article_id"]
        decision={"action":"reject","revision":1,"updated_at":d["updated_at"],"draft_blob_sha":"a"*40}
        self.assertEqual(self.choose(rec,{ident:(d,"a"*40)},{ident+"-r1.json":(decision,"b"*40)})[1]["candidate"]["sequence"],4)
    def test_quota_counts_all_old_worker_receipts(self):
        rec={str(i):{"status":"reserved","worker":"hpii-auto-editor","claimed_at":NOW.isoformat(),"pool_id":"absent","article_id":str(i)} for i in range(5)}
        self.assertEqual(self.choose(receipts=rec)[0],"quota_full")
