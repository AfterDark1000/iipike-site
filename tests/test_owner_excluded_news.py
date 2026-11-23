"""Owner exclusion protects the newsroom from accidental re-ingestion."""
import json
from pathlib import Path
import unittest

from scripts.site_news_pool import (
    EXCLUDED_NEWS_PATH, POOL_PATH, add, validate
)
from scripts.editorial_routing import validate_document, ROUTES, ROOT

SOURCE="https://www.mtu.edu/news/2026/11/less-data-faster-discovery-researchers-rethink-ais-role-in-developing-new-materials.html"
PAPER="https://www.nature.com/articles/s41524-026-02361-x"
REJECTED_ID="n-1788965d91d5bb6a"
REMOVED_REQUEST="auto-20261123-work-ordinary-008.json"

class OwnerExcludedNewsTests(unittest.TestCase):
    def test_excluded_source_and_paper_cannot_reenter_with_new_title(self):
        pool={"schema_version":1,"note":"Test news pool","items":[]}
        candidates=[
            {"title":"New title for removed material-science story","source_url":SOURCE+"?utm_source=scout"},
            {"title":"Changed headline for rejected scientific study","source_url":PAPER},
            {"title":"Unrelated regular story passes","source_url":"https://example.org/new-story"}
        ]
        updated, report=add(pool,candidates,now="2026-11-23T15:00:00Z")
        self.assertEqual(len(updated["items"]),1)
        self.assertEqual(updated["items"][0]["title"],"Unrelated regular story passes")
        self.assertEqual(len(report["duplicates"]),2)
        self.assertEqual(len(report["added"]),1)

    def test_removed_entry_has_no_active_reservation_or_route(self):
        pool=json.loads(POOL_PATH.read_text(encoding="utf-8"))
        routes=json.loads((ROOT/ROUTES).read_text(encoding="utf-8"))
        self.assertNotIn(REJECTED_ID,{x["id"] for x in pool["items"]})
        self.assertNotIn(REJECTED_ID,{x["pool_id"] for x in routes["items"]})
        validate(pool)
        validate_document(routes,pool,require_all=True)
        base=ROOT/"data"/"auto_editor"
        self.assertFalse((base/"requests"/REMOVED_REQUEST).exists())
        self.assertFalse((base/"receipts"/REMOVED_REQUEST).exists())
        excluded=json.loads(EXCLUDED_NEWS_PATH.read_text(encoding="utf-8"))
        self.assertIn(SOURCE,excluded["items"][0]["source_urls"])
        self.assertIn(PAPER,excluded["items"][0]["source_urls"])
        # No renumbering: the historical FIFO sequence #223 retains its ID.
        self.assertIn(223,{x["sequence"] for x in pool["items"]})

if __name__ == "__main__":
    unittest.main()
