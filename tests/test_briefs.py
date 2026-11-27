"""Short-news lane: independent, no images, no accidental publishing of drafts."""
from pathlib import Path
import copy
import hashlib
import json
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET

from scripts import build_briefs as b

ROOT=Path(__file__).resolve().parents[1]

class BriefFeedTests(unittest.TestCase):
    def candidates(self):
        return json.loads((ROOT/"data/briefs/candidates.json").read_text(encoding="utf-8"))["items"]

    def test_first_pilot_is_unpublished_until_exact_human_approval(self):
        candidates=self.candidates()
        # The original pilot has grown; regression tests must accept future briefs.
        self.assertTrue({125,185,226} <= {c["pool_sequence"] for c in candidates})
        self.assertTrue(all(c["status"]=="pending_review" for c in candidates))
        approved=b.released_rows(ROOT)
        approved_slugs={row["slug"] for row in approved}
        output=b.outputs(ROOT)
        html=output[ROOT/"briefs/index.html"]
        home=output[ROOT/"index.html"]
        if not approved:
            self.assertIn("Пока короткие новости готовятся",html)
            self.assertIn("Первая подборка на редакционной проверке",home)
        for c in candidates:
            if c["slug"] not in approved_slugs:
                self.assertNotIn(c["headline"],html)
                self.assertNotIn(c["headline"],home)
        self.assertNotIn("editorial_inbox/stories",home)

    def test_home_news_wire_is_compact_timestamped_and_public_only(self):
        rows = b.released_rows(ROOT)
        wire = b.home_strip(rows)
        css = (ROOT/"assets/briefs.css").read_text(encoding="utf-8")
        self.assertIn('class="brief-home-grid"', (ROOT/"index.html").read_text(encoding="utf-8"))
        self.assertIn(".brief-home-time", css)
        self.assertIn("@media(max-width:830px)", css)
        self.assertEqual(wire.count('class="brief-home-link"'), min(6, len(rows)))
        self.assertNotIn('<img', wire)
        for row in rows[:6]:
            self.assertIn('href="briefs/' + row["slug"] + '/"', wire)
            self.assertIn('datetime="' + row["published_at_utc"] + '"', wire)
            self.assertIn(row["headline"], wire)
        for candidate in self.candidates():
            if candidate["slug"] not in {r["slug"] for r in rows}:
                self.assertNotIn(candidate["headline"], wire)
        self.assertEqual(b.home_strip(rows[:0]).count('class="brief-home-link"'), 0)

    def test_readable_mobile_feed_has_permalinks_and_sources(self):
        css=(ROOT/"assets/briefs.css").read_text(encoding="utf-8")
        index=(ROOT/"briefs/index.html").read_text(encoding="utf-8")
        self.assertIn('@media(max-width:520px)',css)
        self.assertIn('href="feed.xml"',index)
        self.assertIn('HPII_BRIEFS_ITEMS_START',index)
        self.assertIn('rel="canonical"',index)
        self.assertNotIn('<img',index)
        self.assertIn('href="briefs/"',(ROOT/"index.html").read_text(encoding="utf-8"))
        self.assertTrue((ROOT/"admin/briefs/index.html").is_file())
        admin=(ROOT/"admin/briefs/index.html").read_text(encoding="utf-8")
        self.assertIn('pending_review',admin)
        self.assertIn('brief-review-proof',admin)
        self.assertIn('approved.json',admin)

    def fixture(self):
        temp=tempfile.TemporaryDirectory(prefix="hpii-brief-tests-")
        root=Path(temp.name)
        for path in ("data/briefs/candidates.json","data/briefs/approved.json",
                     "data/briefs/released.json","briefs/index.html","index.html","news.json"):
            target=root/path;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/path,target)
        return temp,root

    def publish_row(self,c):
        return {k:c[k] for k in ("slug","pool_id","pool_sequence","headline","topic","event_date",
                                  "source","source_url","body")} | {
            "status":"editor_approved","approved_by":"human_editor",
            "approval_ref":"https://github.com/AfterDark1000/iipike-site/issues/99999",
            "approved_at_utc":"2026-11-18T06:00:00Z",
            "published_at_utc":"2026-11-18T07:00:00Z"
        }

    def test_approved_one_generates_distinct_page_rss_and_source(self):
        temp,root=self.fixture()
        try:
            c=self.candidates()[0]
            a=json.loads((root/b.APPROVED).read_text(encoding="utf-8"))
            a["items"]=[self.publish_row(c)]
            (root/b.APPROVED).write_text(json.dumps(a,ensure_ascii=False),encoding="utf-8")
            (root/"data/briefs/released.json").write_text(json.dumps({
                "schema_version":1,"note":"fixture",
                "items":[{"slug":c["slug"],"published_at_utc":"2026-11-18T07:00:00Z"}]
            }),encoding="utf-8")
            rows=b.validated(root)
            self.assertEqual(len(rows),1)
            out=b.outputs(root)
            self.assertIn(root/"briefs"/c["slug"]/"index.html",out)
            page=out[root/"briefs"/c["slug"]/"index.html"]
            self.assertIn(c["body"],page)
            self.assertIn(c["source_url"].replace("&","&amp;"),page)
            self.assertNotIn("<img",page)
            self.assertNotIn("fact_check",page)
            self.assertNotIn(c["fact_check"],page)
            self.assertIn("/briefs/"+c["slug"]+"/",page)
            self.assertIn(c["headline"],out[root/"briefs/index.html"])
            self.assertIn(c["headline"],out[root/"index.html"])
            channel=ET.fromstring(out[root/"briefs/feed.xml"])
            self.assertEqual(len(channel.findall("./channel/item")),1)
            self.assertEqual(channel.findtext("./channel/item/link"),
                             "https://iipike.ru/briefs/"+c["slug"]+"/")
        finally:temp.cleanup()

    def test_unapproved_wrong_text_duplicate_and_bad_url_fail_closed(self):
        temp,root=self.fixture()
        try:
            row=self.publish_row(self.candidates()[0])
            path=root/b.APPROVED
            def expect_bad(mutate):
                bad=copy.deepcopy(row);mutate(bad)
                path.write_text(json.dumps({"schema_version":1,"items":[bad]},ensure_ascii=False))
                with self.assertRaises(ValueError):
                    b.validated(root)
            expect_bad(lambda x:x.update({"status":"pending_review"}))
            expect_bad(lambda x:x.update({"approved_by":"hpii-auto-editor"}))
            expect_bad(lambda x:x.update({"approval_ref":"https://example.org/ok"}))
            expect_bad(lambda x:x.update({"body":"Подменённый текст после утверждения."}))
            expect_bad(lambda x:x.update({"source_url":"javascript:alert(1)"}))
            row["body"]=row["body"]+" "
            path.write_text(json.dumps({"schema_version":1,"items":[row,row]},ensure_ascii=False))
            with self.assertRaises(ValueError):
                b.validated(root)
        finally:temp.cleanup()

    def test_robotics_is_a_valid_brief_topic(self):
        temp,root=self.fixture()
        try:
            c=copy.deepcopy(self.candidates()[0])
            c["topic"]="Робототехника"
            (root/b.CANDIDATES).write_text(json.dumps({
                "schema_version":1,"items":[c]
            },ensure_ascii=False),encoding="utf-8")
            row=self.publish_row(c)
            (root/b.APPROVED).write_text(json.dumps({
                "schema_version":1,"items":[row]
            },ensure_ascii=False),encoding="utf-8")
            rows=b.validated(root)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]["topic"],"Робототехника")
            self.assertIn("Робототехника",b.card(rows[0]))
            self.assertIn("Робототехника",b.render_page(rows[0]))
            c["topic"]=row["topic"]="Несуществующая категория"
            (root/b.CANDIDATES).write_text(json.dumps({
                "schema_version":1,"items":[c]
            },ensure_ascii=False),encoding="utf-8")
            (root/b.APPROVED).write_text(json.dumps({
                "schema_version":1,"items":[row]
            },ensure_ascii=False),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"Invalid brief topic"):
                b.validated(root)
        finally:temp.cleanup()

    def test_approval_sha256_changes_when_text_changes(self):
        row=self.publish_row(self.candidates()[0])
        expected=hashlib.sha256(chr(10).join(row[k] for k in
                  ("slug","pool_id","headline","body","source_url")).encode("utf-8")).hexdigest()
        self.assertEqual(b.approval_sha256(row),expected)
        row["body"]+="!"
        self.assertNotEqual(b.approval_sha256(row),expected)

    def test_pool_sync_is_safe_and_idempotent(self):
        from scripts import sync_briefs_pool
        temp,root=self.fixture()
        try:
            c=self.candidates()[0]
            candidate = {
                "id": c["pool_id"],
                "sequence": c["pool_sequence"],
                "title": c["headline"],
                "source_url": c["source_url"],
                "summary": c["body"],
                "origin": "test fixture",
                "priority": "normal",
                "status": "queued",
                "added_at": "2026-11-16T00:00:00Z",
                "review_started_at": None,
                "closed_at": None,
                "article_id": None,
                "note": "",
            }
            pool = {"schema_version": 1, "note": "test fixture", "items": [candidate]}
            (root/"data/site_news_pool.json").write_text(
                json.dumps(pool, ensure_ascii=False), encoding="utf-8"
            )
            a=json.loads((root/b.APPROVED).read_text(encoding="utf-8"))
            a["items"]=[self.publish_row(c)]
            (root/b.APPROVED).write_text(json.dumps(a,ensure_ascii=False),encoding="utf-8")
            (root/"data/briefs/released.json").write_text(json.dumps({
                "schema_version":1,"note":"fixture",
                "items":[{"slug":c["slug"],"published_at_utc":"2026-11-18T07:00:00Z"}]
            }),encoding="utf-8")
            (root/"briefs"/c["slug"]).mkdir(parents=True)
            (root/"briefs"/c["slug"]/"index.html").write_text("rendered",encoding="utf-8")
            out,changes=sync_briefs_pool.synchronized(root)
            self.assertEqual(changes,[c["slug"]])
            item=next(x for x in out["items"] if x["id"]==c["pool_id"])
            self.assertEqual(item["status"],"approved")
            self.assertEqual(item["article_id"],c["slug"])
            (root/"data/site_news_pool.json").write_text(json.dumps(out,ensure_ascii=False),encoding="utf-8")
            _,again=sync_briefs_pool.synchronized(root)
            self.assertEqual(again,[])
        finally:temp.cleanup()

    def test_pool_and_full_article_data_never_mutated_by_brief_generation(self):
        import inspect
        code=inspect.getsource(b)
        self.assertNotIn("site_publication_queue",code)
        self.assertNotIn("HPII_SITE_FIRST_AUTOPUBLISH",code)
        self.assertNotIn("editorial_inbox/stories",code)
        # Outputs are restricted to briefs and the homepage strip, not the full-article catalog.
        self.assertTrue(all(p.name=="index.html" or "/briefs/" in p.as_posix()
                            for p in b.outputs(ROOT)))

    def test_wire_groups_released_briefs_by_actual_local_day(self):
        import re
        from itertools import groupby
        rows = b.released_rows(ROOT)
        from scripts.site_rubrics import listing_markup, listing_days
        html = listing_markup(ROOT/"briefs/index.html")
        for path, page in b.outputs(ROOT).items():
            self.assertEqual(path.read_text(encoding="utf-8"), page)
        self.assertIn('class="home-v1 brief-page brief-wire-page"', html)
        self.assertEqual(re.findall(r'<article class="brief-item" id="([^"]+)">', html),
                         [r["slug"] for r in rows])
        labels = [b.date_label(r["published_at_utc"]) for r in rows]
        self.assertEqual(re.findall(r'<h2 class="brief-day-title">([^<]+)</h2>', html),
                         listing_days(labels))
        self.assertEqual(re.findall(r'<time class="brief-clock" datetime="([^"]+)" aria-label="([^"]+)">([^<]+)</time>', html),
                         [(r["published_at_utc"], label, label.partition(" · ")[2]) for r, label in zip(rows, labels)])
        self.assertNotIn('<img', html)

if __name__=="__main__":
    unittest.main()
