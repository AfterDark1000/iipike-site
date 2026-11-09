"""Regression guard: explicit site-first Dzen links survive altered Dzen titles."""
import datetime as dt
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "openai-images-2-6-gif-20261104":
        ("6aec5f2492fe100941ec10dd", "https://dzen.ru/a/auxfJJL-EAlB7BDd"),
    "thinking-machines-inkling-2-small-20261105":
        ("6aef11f41163a041fcdccfe4", "https://dzen.ru/a/au8R9BFjoEH83M_k"),
}


class ExplicitDzenCounterpartsTests(unittest.TestCase):
    def test_verified_renamed_counterparts_are_durable(self):
        news = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
        by_id = {row.get("id"): row for row in news}
        self.assertEqual(len(by_id), len(news))
        for sid, (dzen_id, url) in EXPECTED.items():
            with self.subTest(id=sid):
                self.assertEqual(by_id[sid].get("site_first_dzen_id"), dzen_id)
                self.assertEqual(by_id[sid].get("site_first_dzen_url"), url)

    def test_no_explicit_counterpart_is_ambiguous(self):
        news = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
        dzen_ids, urls = set(), set()
        for row in news:
            did, url = row.get("site_first_dzen_id"), row.get("site_first_dzen_url")
            if not (did or url):
                continue
            self.assertRegex(did or "", r"^[a-f0-9]{24}$")
            self.assertRegex(url or "", r"^https://dzen\\.ru/a/[A-Za-z0-9_-]+$")
            self.assertNotIn(did, dzen_ids)
            self.assertNotIn(url, urls)
            self.assertTrue(row.get("published_at_utc"))
            dzen_ids.add(did)
            urls.add(url)

    def test_generator_matches_verified_id_not_just_headline(self):
        workflow = (ROOT / ".github/workflows/dzen-reading-queue.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("const byDzenId = new Map()", workflow)
        self.assertIn("siteRow?.site_first_dzen_id", workflow)
        self.assertIn("siteRow?.site_first_dzen_url", workflow)
        self.assertIn("e.dzen_url === explicitUrl && afterSite(e)", workflow)
        self.assertIn("Unverified explicit Dzen counterpart:", workflow)


if __name__ == "__main__":
    unittest.main()
