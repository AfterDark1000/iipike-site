"""GitHub editorial queue page never publishes articles and reflects source refs."""
import datetime as dt
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.render_site_publication_queue import as_markdown, safe_text, scan_queue
from scripts.site_publication_queue import main as schedule_main

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 5, 8, tzinfo=UTC)


class EditorialQueuePageTests(unittest.TestCase):
    def test_markdown_escapes_headlines_and_never_injects_html(self):
        text = safe_text(" [bad] <script>alert(1)</script> | new\nline ")
        self.assertNotIn("<script>", text)
        self.assertIn("&#124;", text)
        self.assertIn("&#91;", text)
        self.assertNotIn("\n", text)

    def test_scan_shows_published_ready_and_waiting_separately(self):
        paths = "\n".join([
            "editorial_inbox/stories/collinear.json",
            "editorial_inbox/covers/collinear.webp",
            "editorial_inbox/stories/hinton.json",
            "editorial_inbox/stories/cnas.json",
            "editorial_inbox/covers/cnas.webp",
        ])
        titles = {
            "collinear": "Collinear: 100 уязвимостей",
            "hinton": "Хинтон: Чернобыль ИИ",
            "cnas": "ИИ-агенты могут стать неотключаемыми",
        }
        def fake_blob(ref, path):
            if path == "news.json":
                return json.dumps([{
                    "id": "cnas", "published_at_utc": "2026-11-05T07:00:00Z",
                }])
            sid = path.split("/")[-1].replace(".json", "")
            return json.dumps({"id": sid, "title": titles[sid],
                               "status": "editor_approved",
                               "approved_by": "human_editor"})
        def fake_exists(ref, path):
            return path == "articles/cnas/index.html"

        with patch("scripts.render_site_publication_queue.git",
                   return_value=SimpleNamespace(stdout=paths)), \
             patch("scripts.render_site_publication_queue.safe_git_blob_at",
                   side_effect=fake_blob), \
             patch("scripts.render_site_publication_queue.exists_at",
                   side_effect=fake_exists), \
             patch("scripts.render_site_publication_queue.latest_site_first_publication",
                   return_value=NOW - dt.timedelta(minutes=50)), \
             patch("scripts.render_site_publication_queue._last_change",
                   return_value=NOW - dt.timedelta(hours=1)):
            rows, last = scan_queue(now=NOW)
        self.assertEqual({r["id"]: r["status"] for r in rows}, {
            "cnas": "✅ Опубликована",
            "collinear": "🟢 Готова к выпуску",
            "hinton": "🖼️ Ждёт обложку",
        })
        page = as_markdown(rows, last)
        self.assertIn("Collinear", page)
        self.assertIn("Хинтон", page)
        self.assertIn("Опубликована", page)
        self.assertIn("https://iipike.ru/articles/cnas/", page)
        self.assertIn("Репозиторий публичный", page)
        self.assertNotIn("<script>", page)

    def test_explicit_future_schedule_displays_but_does_not_fake_publication(self):
        row = {
            "id": "future",
            "title": "Запланированный выпуск",
            "status": "🕒 Ожидает заданного времени",
            "published": False,
            "ready_at": NOW,
            "publish_at": NOW + dt.timedelta(hours=4),
            "source_path": "editorial_inbox/stories/future.json",
            "cover_path": "editorial_inbox/covers/future.webp",
            "published_at": None,
        }
        text = as_markdown([row], None)
        self.assertIn("не ранее 05.11.2026 17:00", text)
        self.assertNotIn("https://iipike.ru/articles/future/", text)

    def test_inspect_only_does_not_publish_eligible_story(self):
        env = {
            "GITHUB_REPOSITORY": "AfterDark1000/iipike-site",
            "HPII_SITE_FIRST_SCHEDULER": "1",
            "HPII_SITE_FIRST_AUTOPUBLISH": "1",
            "HPII_TARGET_STORY_ID": "",
            "HPII_URGENT_STORY": "false",
            "HPII_QUEUE_INSPECT_ONLY": "true",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
        }
        with patch.dict("os.environ", env), \
             patch("scripts.site_publication_queue.git",
                   return_value=SimpleNamespace(stdout="valid")), \
             patch("scripts.site_publication_queue.safe_git_blob_at",
                   return_value="[]"), \
             patch("scripts.site_publication_queue.ready_items",
                   return_value=[{"id": "collinear"}]), \
             patch("scripts.site_publication_queue.select_one") as select, \
             patch("scripts.site_publication_queue.release_one") as release:
            schedule_main()
            select.assert_not_called()
            release.assert_not_called()

    def test_automated_schedule_cannot_disable_publication_by_injected_env(self):
        env = {
            "GITHUB_REPOSITORY": "AfterDark1000/iipike-site",
            "HPII_SITE_FIRST_SCHEDULER": "1",
            "HPII_SITE_FIRST_AUTOPUBLISH": "1",
            "HPII_QUEUE_INSPECT_ONLY": "true",
            "HPII_URGENT_STORY": "false",
            "GITHUB_EVENT_NAME": "schedule",
        }
        with patch.dict("os.environ", env):
            with self.assertRaisesRegex(ValueError, "manually"):
                schedule_main()


if __name__ == "__main__":
    unittest.main()
