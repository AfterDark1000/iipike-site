import json
import tempfile
import unittest
from pathlib import Path
from scripts import site_dossier as d

class DossierTests(unittest.TestCase):
    def setUp(self):
        self.row={"id":"one","url":"articles/one/","title":"Story <&>","summary":"Summary","cover":"assets/editorial/one.webp","published":"2026-11-25","rubric":"news"}
    def test_only_published_rows(self):
        self.assertEqual(d.rows_for([self.row],["one"]),[self.row])
        for bad in ("draft","../one"):
            with self.assertRaises(ValueError): d.rows_for([self.row],[bad])
    def test_escape_and_relative_links(self):
        h=d.archive([self.row],["one"])
        self.assertIn('href="../articles/one/"',h)
        self.assertIn('src="../assets/editorial/one.webp"',h)
        self.assertIn("Story &lt;&amp;&gt;",h)
        self.assertIn('rel="canonical" href="https://iipike.ru/dossier/"',h)
        self.assertEqual(d.home_section([],[]), "")
        self.assertNotIn('class="dossier-card"',d.archive([],[]))
    def test_header_decoration_is_reversible_and_idempotent(self):
        old='<main><p class="kicker">News</p><figure class="cover"><img src="original"></figure><article>Text</article></main>'
        new=d.mark_article(old,"one",["one"])
        self.assertEqual(new.count('class="dossier-article-marker"'),1)
        self.assertEqual(d.mark_article(new,"one",["one"]),new)
        self.assertEqual(d.mark_article(new,"one",[]),old)
        self.assertEqual(new.split('<figure',1)[1],old.split('<figure',1)[1])
    def test_config_rejects_invalid_or_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=root/d.PATH;path.parent.mkdir()
            for items in (["one","one"],["../../bad"],["https://bad"],[None]):
                path.write_text(json.dumps({"schema_version":1,"items":items}))
                with self.assertRaises(ValueError):d.load_ids(root)
            path.write_text(json.dumps({"schema_version":1,"items":["one"]}))
            self.assertEqual(d.load_ids(root),["one"])
    def test_home_only_replaces_its_owned_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=root/d.PATH;path.parent.mkdir()
            path.write_text(json.dumps({"schema_version":1,"items":["one"]}))
            old="BEFORE"+d.START+"old"+d.END+"AFTER"
            new=d.update_home_dossier(old,[self.row],root)
            self.assertTrue(new.startswith("BEFORE"+d.START))
            self.assertTrue(new.endswith(d.END+"AFTER"))
            self.assertIn('href="articles/one/"',new)
            self.assertEqual(d.update_home_dossier(new,[self.row],root),new)
            path.write_text(json.dumps({"schema_version":1,"items":[]}))
            self.assertEqual(d.update_home_dossier(new,[self.row],root),"BEFORE"+d.START+"\n\n"+d.END+"AFTER")

    def test_home_manual_showcase_keeps_six_and_archive_keeps_all(self):
        rows=[dict(self.row,id=f"story-{i}",url=f"articles/story-{i}/") for i in range(8)]
        ids=[r["id"] for r in rows]
        markup=d.home_section(rows,ids)
        self.assertEqual(markup.count('class="dossier-slide"'),6)
        self.assertEqual(markup.count('class="dossier-thumb"'),6)
        self.assertIn('1 / 6',markup)
        self.assertIn('src="assets/dossier-showcase.js"',markup)
        self.assertNotIn('href="articles/story-6/"',markup)
        self.assertNotIn('dossier-controls',d.home_section(rows,ids[:1]))
        self.assertIn('data-count="8"',d.archive(rows,ids))
        self.assertEqual(d.archive(rows,ids).count('class="dossier-card"'),8)
