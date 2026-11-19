"""Regression tests for paced short news, no network and no live writes."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts import build_briefs, release_one_brief

ROOT = Path(__file__).resolve().parents[1]


class BriefPacingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for rel in ("data/briefs/candidates.json", "data/briefs/approved.json",
                    "data/briefs/released.json", "news.json",
                    "briefs/index.html", "index.html"):
            dest = self.root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, dest)
        self.known = {r["pool_sequence"]: r for r in build_briefs.validated(self.root)}

    def t(self, raw):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))

    def test_new_five_remain_private_until_each_independent_release(self):
        self.assertEqual(len(build_briefs.validated(self.root)), 8)
        self.assertEqual(len(build_briefs.released_rows(self.root)), 3)
        index = build_briefs.outputs(self.root)[self.root / "briefs/index.html"]
        self.assertNotIn(self.known[59]["headline"], index)
        updated, slug, status = release_one_brief.release_one(
            self.root, now=self.t("2026-11-19T07:05:00Z"))
        self.assertEqual((slug, status), (self.known[59]["slug"], "released_one"))
        (self.root / release_one_brief.RELEASED).write_text(
            json.dumps(updated, ensure_ascii=False), encoding="utf-8")
        visible = build_briefs.released_rows(self.root)
        self.assertEqual(len(visible), 4)
        self.assertEqual(visible[0]["slug"], slug)
        self.assertEqual(visible[0]["published_at_utc"], "2026-11-19T07:05:00Z")
        html = build_briefs.outputs(self.root)[self.root / "briefs/index.html"]
        self.assertIn(self.known[59]["headline"], html)
        self.assertNotIn(self.known[63]["headline"], html)
        self.assertIn("12:05", html)  # local site timestamp UTC+05

    def test_second_release_requires_new_quarter_and_full_gap(self):
        updated, slug, _ = release_one_brief.release_one(
            self.root, now=self.t("2026-11-19T07:03:00Z"))
        self.assertEqual(slug, self.known[59]["slug"])
        (self.root / release_one_brief.RELEASED).write_text(json.dumps(updated))
        _, other, status = release_one_brief.release_one(
            self.root, now=self.t("2026-11-19T07:14:55Z"))
        self.assertIsNone(other)
        self.assertEqual(status, "slot_already_used")
        _, other, status = release_one_brief.release_one(
            self.root, now=self.t("2026-11-19T07:15:00Z"))
        self.assertIsNone(other)
        self.assertEqual(status, "minimum_gap")
        _, other, status = release_one_brief.release_one(
            self.root, now=self.t("2026-11-19T07:18:00Z"))
        self.assertEqual((other, status), (self.known[63]["slug"], "released_one"))

    def test_pause_overnight_local_even_with_approved_backlog(self):
        _, slug, reason = release_one_brief.release_one(
            self.root, now=self.t("2026-11-19T23:00:00Z"))
        self.assertEqual((slug, reason), (None, "night_pause"))
        _, slug, reason = release_one_brief.release_one(
            self.root, now=self.t("2026-11-20T02:05:00Z"))
        self.assertEqual(reason, "released_one")
        self.assertEqual(slug, self.known[59]["slug"])

    def test_forged_and_duplicate_release_manifest_rejected(self):
        path = self.root / release_one_brief.RELEASED
        original = json.loads(path.read_text())
        bad = dict(original)
        bad["items"] = original["items"] + [{"slug": "made-up-unapproved",
                                             "published_at_utc": "2026-11-19T07:00:00Z"}]
        path.write_text(json.dumps(bad))
        with self.assertRaisesRegex(ValueError, "Unapproved"):
            build_briefs.released_rows(self.root)
        bad["items"] = original["items"] + [original["items"][0]]
        path.write_text(json.dumps(bad))
        with self.assertRaisesRegex(ValueError, "Unapproved"):
            build_briefs.released_rows(self.root)


if __name__ == "__main__":
    unittest.main()
