"""Offline safety tests: Dzen publication detection never edits editor Markdown."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sync_site_first_dzen as sync

SLUG = "new-first-20261105"
URL = "https://dzen.ru/a/auC5RL9TIlQwHobn"
ID = "6ae0b944bf532254301e86e7"


class SiteFirstDzenLinkSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "content" / "approved").mkdir(parents=True)
        (self.root / "editorial_inbox" / "stories").mkdir(parents=True)
        (self.root / "articles" / SLUG).mkdir(parents=True)
        self.article = {
            "id": SLUG, "url": "articles/" + SLUG + "/",
            "title": "ИИ-агенты могут стать неотключаемыми",
            "published": "2026-11-05",
            "published_at_utc": "2026-11-05T03:00:00Z",
        }
        self.records = [self.article]
        self.catalog_row = {
            "dzen_id": ID, "dzen_url": URL,
            "title": self.article["title"],
            "published_at_utc": "2026-11-05T04:00:00+00:00",
            "url_evidence": "recorded_in_editorial_archive",
            "title_evidence": "recorded",
        }
        self.catalog = {"schema_version": 1, "entries": [self.catalog_row]}
        self.raw = "Утверждённый текст с [перелинковкой](" + URL + ")."
        self.approved = {
            "slug": SLUG, "title": self.article["title"],
            "status": "approved", "article_markdown": self.raw,
            "published_at_utc": self.article["published_at_utc"]
        }
        self.inbox = {
            "id": SLUG, "title": self.article["title"],
            "status": "editor_approved", "approved_by": "human_editor",
            "article_markdown": self.raw
        }
        self._write()

    def _write(self):
        (self.root / "news.json").write_text(
            json.dumps(self.records, ensure_ascii=False), encoding="utf-8")
        (self.root / "content" / "approved" / (SLUG + ".json")).write_text(
            json.dumps(self.approved, ensure_ascii=False), encoding="utf-8")
        (self.root / "editorial_inbox" / "stories" / (SLUG + ".json")).write_text(
            json.dumps(self.inbox, ensure_ascii=False), encoding="utf-8")
        (self.root / "articles" / SLUG / "index.html").write_text(
            '<a href="' + URL + '">Читайте</a>', encoding="utf-8")

    def test_verified_unique_exact_title_only(self):
        found = sync.matches(self.root, self.records, self.catalog)
        self.assertEqual(found[SLUG]["dzen_url"], URL)
        altered = dict(self.catalog_row, title="ИИ-агенты: иная новость")
        self.assertEqual(sync.matches(self.root, self.records,
                                      {"schema_version": 1, "entries": [altered]}), {})
        same_after_casefold = dict(self.catalog_row, title="  ии-АГЕНТЫ могут стать неотключаемыми  ")
        self.assertEqual(sync.matches(self.root, self.records,
                                      {"schema_version": 1, "entries": [same_after_casefold]})[SLUG]["dzen_id"], ID)

    def test_fail_closed_for_ambiguous_or_unverified_or_older_dzen_story(self):
        other = dict(self.catalog_row, dzen_id="6ad9b0b5dda2334495a69bf0",
                     dzen_url="https://dzen.ru/a/atmwtd2iM0SVppvw")
        duplicate = {"schema_version": 1, "entries": [self.catalog_row, other]}
        self.assertEqual(sync.matches(self.root, self.records, duplicate), {})
        untrusted = dict(self.catalog_row, url_evidence="derived_from_unverified_seen_id")
        self.assertEqual(sync.matches(self.root, self.records,
                                      {"schema_version": 1, "entries": [untrusted]}), {})
        older = dict(self.catalog_row, published_at_utc="2026-11-04T04:00:00Z")
        self.assertEqual(sync.matches(self.root, self.records,
                                      {"schema_version": 1, "entries": [older]}), {})

    def test_conflict_and_unapproved_content_never_auto_link(self):
        already = dict(self.article, id="another-story", dzen_id=ID, dzen_url=URL)
        with self.assertRaisesRegex(ValueError, "already assigned"):
            sync.matches(self.root, self.records + [already], self.catalog)
        self.inbox["article_markdown"] = "Иной текст: изменён после утверждения."
        self._write()
        self.assertEqual(sync.matches(self.root, self.records, self.catalog), {})

    def test_plan_changes_only_index_and_relevant_html_not_approved_text(self):
        old_source = (self.root / "content" / "approved" / (SLUG + ".json")).read_bytes()
        old_inbox = (self.root / "editorial_inbox" / "stories" / (SLUG + ".json")).read_bytes()
        old_index = (self.root / "news.json").read_bytes()
        target = '<a href="https://iipike.ru/articles/' + SLUG + '/">Читайте</a>'
        with patch.object(sync, "approved_article", return_value=self.approved), \
             patch.object(sync, "render_article", return_value=target):
            found, changes = sync.plan(self.root, self.catalog)
        self.assertEqual(list(found), [SLUG])
        self.assertEqual(len(changes), 2)
        self.assertIn('"site_first_dzen_url": "' + URL + '"',
                      changes[self.root / "news.json"])
        self.assertEqual(changes[self.root / "articles" / SLUG / "index.html"], target)
        self.assertEqual((self.root / "news.json").read_bytes(), old_index)
        self.assertEqual((self.root / "content" / "approved" / (SLUG + ".json")).read_bytes(), old_source)
        self.assertEqual((self.root / "editorial_inbox" / "stories" / (SLUG + ".json")).read_bytes(), old_inbox)

    def test_earliest_site_first_pilot_with_paragraphs_is_supported(self):
        blocks = [{"type": "lead", "text": "Проверенное вступление."},
                  {"type": "p", "text": "Продолжение статьи."}]
        self.approved.pop("article_markdown")
        self.inbox.pop("article_markdown")
        self.approved["paragraphs"] = blocks
        self.inbox["paragraphs"] = blocks
        self._write()
        self.assertEqual(sync.matches(self.root, self.records, self.catalog)[SLUG]["dzen_id"], ID)

    def test_idempotent_after_link_registered(self):
        self.records[0]["site_first_dzen_id"] = ID
        self.records[0]["site_first_dzen_url"] = URL
        self._write()
        found, changed = sync.plan(self.root, self.catalog)
        self.assertEqual(found, {})
        self.assertEqual(changed, {})

    def test_invalid_catalog_rejected(self):
        for catalog in ({}, {"schema_version": 1, "entries": "bad"}):
            with self.assertRaisesRegex(ValueError, "Invalid published"):
                sync.matches(self.root, self.records, catalog)


if __name__ == "__main__":
    unittest.main()
