import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from scripts import auto_artist_dispatch as d

NOW = datetime(2026,11,25,11,0,tzinfo=timezone.utc)

class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.inbox=self.root/"editorial_inbox"
    def put(self,folder,name,obj):
        p=self.inbox/folder/(name+".json")
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(obj),encoding="utf-8")
        return d.blob(p)
    def draft(self,sid,seq=1,rev=1,status="ready_for_review"):
        return self.put("auto_drafts",sid,{"article_id":sid,"revision":rev,
            "status":status,"updated_at":d.iso(NOW-timedelta(hours=2)),
            "pool_sequence":seq,"content":{"title":sid,"article_markdown":"A complete article."},
            "cover_brief":{"fact":"fact"}})
    def approve(self,sid,sha,rev=1):
        return self.put("auto_decisions",f"{sid}-r{rev}",{"article_id":sid,"revision":rev,
            "action":"approve_text","status":"text_approved_cover_pending","draft_blob_sha":sha,
            "updated_at":d.iso(NOW-timedelta(hours=2)),"decided_by":"AfterDark1000"})
    def cover(self,sid,sha,rev=1,ver=1,when=None,revise=False):
        k=f"{sid}-r{rev}-v{ver}"
        p=self.inbox/"auto_covers"/(k+".webp")
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(b"fixture bytes for identity only")
        image=d.blob(p)
        m=self.put("auto_covers",k,{"article_id":sid,"text_revision":rev,
            "source_draft_blob_sha":sha,"image_blob_sha":image,
            "created_at":d.iso(when or NOW-timedelta(hours=2))})
        if revise:
            self.put("auto_cover_decisions",k,{"article_id":sid,"text_revision":rev,
                "cover_version":ver,"action":"revise_cover","status":"cover_revision_requested",
                "decided_by":"AfterDark1000","source_draft_blob_sha":sha,
                "text_updated_at":d.iso(NOW-timedelta(hours=2)),
                "cover_metadata_blob_sha":m,"cover_blob_sha":image,"note":"Different concept"})
        return k
    def claim(self,k,when):
        self.put("auto_artist_dispatch/claims",k,{"schema_version":1,"stem":k,
            "state":"generation_reserved","reserved_at":d.iso(when)})
    def build(self,holds=(),parallel=True,published=()):
        return d.build(self.root,set(published),list(holds),NOW,parallel)
    def test_fifo_and_return_priority(self):
        self.draft("first",1)
        sha=self.draft("return",2)
        self.cover("return",sha,revise=True)
        j=self.build()["job"]
        self.assertEqual(j["stem"],"return-r1-v2")
        self.assertEqual(j["previous"]["note"],"Different concept")
        self.claim(j["stem"],NOW)
        b=self.build()
        self.assertEqual(b["job"]["stem"],"first-r1-v1")
        self.assertEqual(b["waiting_for_manual_upload"][0]["stem"],j["stem"])
    def test_hold_does_not_stop_queue(self):
        self.draft("first",1)
        self.draft("second",2)
        b=self.build([{"stem":"first-r1-v1","recorded_at":d.iso(NOW)}])
        self.assertEqual(b["quota"]["used"],1)
        self.assertEqual(b["job"]["stem"],"second-r1-v1")
    def test_rolling_quota_and_no_double_count(self):
        self.draft("next",20)
        for i in range(5):
            sid=f"old-{i}"
            sha=self.draft(sid,i)
            k=self.cover(sid,sha,when=NOW-timedelta(hours=3))
            self.claim(k,NOW-timedelta(hours=4))
        b=self.build()
        self.assertEqual(b["quota"]["used"],5)
        self.assertEqual(b["status"],"quota_full")
        self.assertIsNone(b["job"])
    def test_old_claim_stays_reserved_but_does_not_count_today(self):
        self.draft("first",1)
        self.draft("second",2)
        self.claim("first-r1-v1",NOW-timedelta(hours=25))
        b=self.build()
        self.assertEqual(b["quota"]["used"],0)
        self.assertEqual(b["job"]["stem"],"second-r1-v1")
    def test_approval_required_if_parallel_not_live(self):
        self.draft("first",1)
        sha=self.draft("second",2)
        self.approve("second",sha)
        self.assertEqual(self.build(parallel=False)["job"]["article_id"],"second")
    def test_skip_invalid_or_published_or_handed_off(self):
        self.draft("published",1)
        self.draft("reject",2)
        self.put("auto_decisions","reject-r1",{"action":"reject"})
        self.draft("handoff",3)
        self.put("auto_handoffs","handoff-r1-v1",{})
        self.draft("drafting",4,status="drafting")
        sha=self.draft("bad-return",5)
        self.cover("bad-return",sha,revise=True)
        self.draft("bad-return",6) # changes source blob: old return cannot be reused
        self.draft("good",7)
        self.assertEqual(self.build(published=["published"])["job"]["article_id"],"good")
    def test_invalid_ledger_fails_closed(self):
        self.put("auto_artist_dispatch/claims","bad",{"reserved_at":d.iso(NOW)})
        with self.assertRaises(ValueError):
            self.build()

if __name__=="__main__":
    unittest.main()
