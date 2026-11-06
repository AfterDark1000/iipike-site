"""Regression: preserve Dzen source while resolving explicit site-first crosslinks."""
import datetime as dt
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.site_related import (
    canonical_dzen_url, explicit_site_crosslinks, render_links, validate_links,
)
from scripts.publish_approved_article import render_article
from scripts.site_publication_queue import ready_items
from scripts.render_site_publication_queue import scan_queue

IDENT = "6aec5fa092fe100941ed2933"
DZEN = "https://dzen.ru/a/auxfoJL-EAlB7Skz"
TARGET = "openai-linux-root-948-20261104"
SLUG = "gpt-6-cyber-firefox-81-vulnerabilities-20261105"
LOCAL = "https://iipike.ru/articles/" + TARGET + "/"
RECORD = {"id": TARGET, "url": "articles/" + TARGET + "/",
          "title": "ИИ OpenAI нашёл 948 способов получить root в Linux"}
SOURCE = ("Ранее мы [рассказывали о 948 уязвимостях Linux](" + DZEN +
          "). Текст для Дзена со ссылкой на Дзен.")


def editorial():
    return {"id": SLUG, "title": "GPT-6 Cyber и Firefox",
            "status": "editor_approved", "approved_by": "human_editor",
            "related_dzen_ids": [IDENT],
            "site_crosslinks": {IDENT: TARGET},
            "article_markdown": SOURCE}


class SiteFirstCrosslinkTests(unittest.TestCase):
    def test_approved_dzen_source_is_untouched_but_site_html_uses_site_target(self):
        self.assertEqual(canonical_dzen_url(IDENT), DZEN)
        story = editorial()
        before = json.dumps(story, ensure_ascii=False, sort_keys=True)
        mapped = explicit_site_crosslinks(story, [RECORD])
        self.assertEqual(mapped[IDENT], RECORD)
        validate_links(story["related_dzen_ids"], {}, site_crosslinks=mapped)
        related = render_links(story["related_dzen_ids"], [RECORD], {},
                               site_crosslinks=mapped)
        self.assertIn("../../articles/" + TARGET + "/", related)
        self.assertNotIn(DZEN, related)

        page_data = {
            **story, "slug": SLUG, "summary": "Краткая аннотация",
            "rubric": "news", "section": "НОВОСТИ ИИ",
            "published": "2026-11-06",
            "cover": "assets/editorial/test.webp",
            "source_url": "https://openai.com/index/introducing-gpt-6-cyber/",
            "source_title": "OpenAI",
            "paragraphs": [
                {"type": "lead", "text": "Вышла новая модель OpenAI."},
                {"type": "p", "text": SOURCE},
            ],
        }
        rendered = render_article(page_data, records=[RECORD], catalog={})
        self.assertIn('href="' + LOCAL + '"', rendered)
        self.assertNotIn('href="' + DZEN + '"', rendered)
        self.assertEqual(story["article_markdown"], SOURCE)
        self.assertEqual(json.dumps(story, ensure_ascii=False, sort_keys=True), before)
        self.assertEqual(page_data["paragraphs"][1]["text"], SOURCE)

    def test_unverified_dzen_reference_without_site_mapping_stays_blocked(self):
        with self.assertRaisesRegex(ValueError, "Unverified Dzen article reference"):
            validate_links([IDENT], {}, site_crosslinks={})

    def test_malformed_unapproved_or_missing_site_targets_never_resolve(self):
        for delta, catalog in (
            ({"site_crosslinks": {IDENT: "invented-site-story"}}, [RECORD]),
            ({"site_crosslinks": {"bad-id": TARGET}}, [RECORD]),
            ({"related_dzen_ids": []}, [RECORD]),
            ({"article_markdown": "Нет согласованной ссылки"}, [RECORD]),
            ({"site_crosslinks": {IDENT: SLUG}}, [RECORD]),
            ({"site_crosslinks": {IDENT: TARGET}}, []),
            ({"site_crosslinks": {IDENT: "https://evil.example/"}}, [RECORD]),
        ):
            story = {**editorial(), **delta}
            with self.subTest(delta=delta, catalog=catalog), self.assertRaises(ValueError):
                explicit_site_crosslinks(story, catalog)

    def test_cron_scheduler_and_dashboard_both_recognize_site_mapping(self):
        tree = ("editorial_inbox/stories/" + SLUG + ".json\n"
                "editorial_inbox/covers/" + SLUG + ".webp\n")
        def blob(ref, path):
            if path == "news.json":
                return json.dumps([RECORD])
            if path.endswith(".json"):
                return json.dumps(editorial(), ensure_ascii=False)
            raise AssertionError(path)
        ready_at = dt.datetime(2026, 11, 6, 9, 0, tzinfo=dt.timezone.utc)
        with patch("scripts.site_publication_queue.git",
                   return_value=SimpleNamespace(stdout=tree)), \
             patch("scripts.site_publication_queue.exists_at", return_value=False), \
             patch("scripts.site_publication_queue.safe_git_blob_at",
                   side_effect=blob), \
             patch("scripts.site_publication_queue._last_change", return_value=ready_at), \
             patch("scripts.site_publication_queue.catalog_entries",
                   return_value={}):
            items = ready_items()
        self.assertEqual([row["id"] for row in items], [SLUG])

        with patch("scripts.render_site_publication_queue.git",
                   return_value=SimpleNamespace(stdout=tree)), \
             patch("scripts.render_site_publication_queue.exists_at", return_value=False), \
             patch("scripts.render_site_publication_queue.safe_git_blob_at",
                   side_effect=blob), \
             patch("scripts.render_site_publication_queue.latest_site_first_publication",
                   return_value=None), \
             patch("scripts.render_site_publication_queue._last_change",
                   return_value=ready_at), \
             patch("scripts.render_site_publication_queue.catalog_entries",
                   return_value={}):
            rows, last = scan_queue(now=ready_at + dt.timedelta(hours=1))
        self.assertIsNone(last)
        self.assertTrue(rows[0]["eligible"])
        self.assertNotIn("Заблокирована", rows[0]["status"])

    def test_existing_provenance_still_validated_strictly(self):
        with self.assertRaisesRegex(ValueError, "Unverified Dzen article reference"):
            validate_links([IDENT], {})
        with self.assertRaises(ValueError):
            explicit_site_crosslinks({**editorial(), "dzen_id": "6ae000000000000000000000"}, [RECORD])


if __name__ == "__main__":
    unittest.main()
