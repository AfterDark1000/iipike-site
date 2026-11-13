"""Editorial homepage picks: publication safety, layout, and deterministic rebuild."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.site_home import (
    FOCUS_END, FOCUS_START, active_focus_ids, load_focus_items,
    render_focus_section, sorted_published, update_home,
)

ROOT = Path(__file__).resolve().parents[1]


class FocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.items = load_focus_items(ROOT)

    def test_four_rubric_cards_and_responsive_layout(self):
        css = (ROOT / "assets" / "site.css").read_text(encoding="utf-8")
        self.assertIn('.home-focus-grid[data-count="4"]', css)
        self.assertIn("grid-template-columns:repeat(4,minmax(0,1fr))", css)
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))", css)
        self.assertIn('aspect-ratio:16/9', css)
        self.assertIn("grid-template-columns:1fr", css)

    def test_four_published_rubric_stories_and_order(self):
        ids = active_focus_ids(self.records, self.items)
        # The editorial picks change over time. Test the CURRENT config,
        # not four permanently pinned story IDs from an old editorial choice.
        configured_ids = [item["id"] for item in self.items]
        self.assertEqual(len(configured_ids), 4)
        self.assertEqual(len(set(configured_ids)), 4)
        self.assertEqual(ids, configured_ids)
        from scripts.site_rubrics import RUBRICS
        by_id = {row["id"]: row for row in self.records}
        self.assertTrue(all(sid in by_id for sid in ids),
                        "Focus picks must exist in the public news catalog")
        rubrics = ["skynet", "news", "what-are-you-doing", "quotes"]
        self.assertEqual([by_id[sid]["rubric"] for sid in ids], rubrics)
        self.assertEqual([item["label"] for item in self.items],
                         [RUBRICS[k]["name"] for k in rubrics])
        self.assertEqual(len(self.html.split(FOCUS_START)), 2)
        self.assertEqual(len(self.html.split(FOCUS_END)), 2)
        self.assertIn('class="home-focus-grid" data-count="4"', self.html)
        self.assertEqual(self.html.count('class="home-focus-card '), 4)
        focus_html = self.html.split(FOCUS_START, 1)[1].split(FOCUS_END, 1)[0]
        positions = [focus_html.index('href="articles/' + sid + '/"') for sid in ids]
        self.assertEqual(positions, sorted(positions),
                         "Homepage must render chosen articles in rubric order")
        self.assertLess(self.html.index('id="focus"'), self.html.index('id="archive"'))
        self.assertLess(self.html.index('id="archive"'), self.html.index('id="latest"'))
        self.assertIn('<a href="#focus">В фокусе</a>', self.html)
        self.assertIn('href="#focus">Главное сегодня', self.html)

    def test_focus_links_are_only_published_first_party(self):
        section = self.html.split(FOCUS_START)[1].split(FOCUS_END)[0]
        for sid in active_focus_ids(self.records, self.items):
            self.assertIn('href="articles/' + sid + '/"', section)
            self.assertNotIn('href="articles/' + sid + '/"', self.html.split(FOCUS_END)[1].split("<!-- HPII_PUBLISHED_SECTION_END -->")[0])
        self.assertNotIn('href="https://', section)
        self.assertNotIn('href="drafts/', section)

    def test_picks_persist_until_editor_replaces_them(self):
        section = self.html.split(FOCUS_START)[1].split(FOCUS_END)[0]
        self.assertNotIn("data-expires-at", section)
        self.assertNotIn("hideExpiredFocus", self.html)
        self.assertNotIn("expires_at", (ROOT / "data/home_focus.json").read_text(encoding="utf-8"))

    def test_rebuild_is_idempotent_for_current_catalog_and_picks(self):
        self.assertEqual(update_home(self.html, self.records, root=ROOT), self.html)

    def test_missing_draft_is_not_exposed_by_pins(self):
        row = dict(self.records[0])
        row["id"] = "unapproved-temporary"
        row["url"] = "articles/unapproved-temporary/"
        row["cover"] = "assets/temporary.webp"
        item = {"id": "unapproved-temporary", "kind": "editor", "label": "Never show"}
        self.assertEqual(render_focus_section(self.records, [item]), "")
        # A proposed draft row is not included in the actually published news.json.
        self.assertNotIn("unapproved-temporary", self.html)

    def test_invalid_config_fails_closed(self):
        for items in (
            [{"id": "bad/../../", "kind": "hot", "label": "Bad"}],
            [{"id": "same", "kind": "editor", "label": "A"},
             {"id": "same", "kind": "editor", "label": "B"}],
            [{"id": "safe", "kind": "hot", "label": "A",
              "expires_at": "2026-11-06T13:00:00+03:00"}],
            [{"id": "safe", "kind": "later", "label": "A"}],
            [{"id": "x", "kind": "editor", "label": "X"}] * 5,
            [{"id": "x", "kind": "editor", "label": "X"}] * 3,
        ):
            with self.subTest(items=items), tempfile.TemporaryDirectory() as folder:
                data = Path(folder) / "data"
                data.mkdir()
                (data / "home_focus.json").write_text(
                    json.dumps({"schema_version": 1, "items": items}),
                    encoding="utf-8",
                )
                with self.assertRaises(ValueError):
                    load_focus_items(folder)

    def test_injected_headline_is_escaped(self):
        sid = "in-news"
        record = {
            "id": sid, "title": 'Alert <script>"not safe"</script>',
            "url": "articles/in-news/", "cover": "assets/safe.webp",
            "published": "2026-11-05", "rubric": "news",
        }
        item = {"id": sid, "kind": "editor", "label": "Безопасно"}
        markup = render_focus_section([record], [item])
        self.assertNotIn("<script>", markup)
        self.assertIn("&lt;script&gt;", markup)
        self.assertIn("articles/in-news/", markup)


if __name__ == "__main__":
    unittest.main()
