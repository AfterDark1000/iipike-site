"""GitHub editorial queue page never publishes articles and reflects source refs."""
import datetime as dt
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.render_site_publication_queue import (as_markdown, safe_text, scan_queue,
                                                   forecast_order, next_cron_tick)
from scripts.site_publication_queue import main as schedule_main

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 5, 8, tzinfo=UTC)


class EditorialQueuePageTests(unittest.TestCase):
    def setUp(self):
        # Unrelated dashboard tests model the queue without real Git refs.
        scoped = patch("scripts.render_site_publication_queue.existing_error", return_value=None)
        scoped.start()
        self.addCleanup(scoped.stop)

    def test_night_forecast_resumes_in_morning_with_hourly_spacing(self):
        local = dt.timezone(dt.timedelta(hours=5))
        now = dt.datetime(2026, 11, 8, 1, 30, tzinfo=local)
        def row(sid):
            return {
                "id": sid, "title": sid, "eligible": True,
                "status": "🌙 Ночная пауза",
                "ready_at": dt.datetime(2026, 11, 8, 0, 0, tzinfo=local),
                "publish_at": None, "published": False,
                "source_path": "editorial_inbox/stories/" + sid + ".json",
                "cover_path": None, "published_at": None,
            }
        rows = [row("first"), row("second"), row("third")]
        forecast = forecast_order(rows, None, now=now)
        self.assertEqual([r["id"] for r, _ in forecast],
                         ["first", "second", "third"])
        self.assertEqual([when.astimezone(local).strftime("%H:%M")
                          for _, when in forecast], ["07:07", "08:07", "09:07"])
        text = as_markdown(rows, None, now=now)
        self.assertIn("Ночная пауза:** 3", text)
        self.assertIn("Не ранее 08.11.2026 07:07", text)
        self.assertIn("Не ранее 08.11.2026 08:07", text)

    def test_next_cron_tick_skips_only_overnight_interval(self):
        local = dt.timezone(dt.timedelta(hours=5))
        for hour, minute, expected in [
            (0, 52, "00:52"), (0, 53, "07:07"),
            (1, 0, "07:07"), (6, 59, "07:07"), (7, 0, "07:07"),
        ]:
            with self.subTest(hour=hour, minute=minute):
                now = dt.datetime(2026, 11, 8, hour, minute, tzinfo=local)
                self.assertEqual(next_cron_tick(now).astimezone(local).strftime("%H:%M"),
                                 expected)

    def test_night_status_is_not_a_publication_blocker(self):
        local = dt.timezone(dt.timedelta(hours=5))
        now = dt.datetime(2026, 11, 8, 3, 0, tzinfo=local)
        paths = ("editorial_inbox/stories/queued.json\n"
                 "editorial_inbox/covers/queued.webp\n")
        def fake_blob(ref, path):
            if path == "news.json":
                return "[]"
            return json.dumps({
                "id": "queued", "title": "Ждёт утра",
                "status": "editor_approved", "approved_by": "human_editor",
            })
        with patch("scripts.render_site_publication_queue.git",
                   return_value=SimpleNamespace(stdout=paths)), \
             patch("scripts.render_site_publication_queue.safe_git_blob_at",
                   side_effect=fake_blob), \
             patch("scripts.render_site_publication_queue.exists_at",
                   return_value=False), \
             patch("scripts.render_site_publication_queue.latest_site_first_publication",
                   return_value=None), \
             patch("scripts.render_site_publication_queue._last_change",
                   return_value=now - dt.timedelta(hours=2)):
            rows, last = scan_queue(now=now)
        self.assertEqual(rows[0]["status"], "🌙 Ночная пауза")
        self.assertTrue(rows[0]["eligible"])
        self.assertEqual(len(forecast_order(rows, last, now=now)), 1)
        page = as_markdown(rows, last, now=now)
        self.assertIn("Ночная пауза", page)
        self.assertIn("Нет проблемных материалов", page)

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
            "collinear": "⏳ Ждёт часовой интервал",
            "hinton": "🖼️ Ждёт обложку",
        })
        page = as_markdown(rows, last)
        self.assertIn("Collinear", page)
        self.assertIn("Хинтон", page)
        self.assertIn("Опубликована", page)
        self.assertIn("https://iipike.ru/articles/cnas/", page)
        self.assertIn("Репозиторий публичный", page)
        self.assertNotIn("<script>", page)

    def test_published_urgent_story_postpones_regular_release_and_dashboard_explains(self):
        paths = "\n".join([
            "editorial_inbox/stories/hinton.json",
            "editorial_inbox/covers/hinton.webp",
        ])
        now = dt.datetime(2026, 11, 5, 11, 15, tzinfo=UTC)
        last = dt.datetime(2026, 11, 5, 10, 41, 13, tzinfo=UTC)
        def fake_blob(ref, path):
            if path == "news.json":
                return json.dumps([
                    {"id":"urgent", "published_at_utc":"2026-11-05T10:41:13Z"}
                ])
            return json.dumps({
                "id":"hinton", "title":"Хинтон о рисках ИИ",
                "status":"editor_approved", "approved_by":"human_editor",
                "site_publish_at":"2026-11-05T13:15:00+05:00"
            })
        with patch("scripts.render_site_publication_queue.git",
                   return_value=SimpleNamespace(stdout=paths)), \
             patch("scripts.render_site_publication_queue.safe_git_blob_at",
                   side_effect=fake_blob), \
             patch("scripts.render_site_publication_queue.exists_at",
                   return_value=False), \
             patch("scripts.render_site_publication_queue.latest_site_first_publication",
                   return_value=last), \
             patch("scripts.render_site_publication_queue._last_change",
                   return_value=now - dt.timedelta(hours=1)):
            rows, stamp = scan_queue(now=now)
        self.assertEqual(stamp, last)
        self.assertEqual(rows[0]["status"], "⏳ Ждёт часовой интервал")
        self.assertEqual(rows[0]["spacing_until"],
                         dt.datetime(2026, 11, 5, 11, 41, 13, tzinfo=UTC))
        page = as_markdown(rows, stamp)
        self.assertIn("Ждут интервал:** 1", page)
        self.assertIn("пауза до 05.11.2026 16:41", page)
        self.assertIn("не ранее 05.11.2026 13:15", page)

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

    def test_forecast_shows_real_order_and_skips_future_slot(self):
        now = dt.datetime(2026, 11, 6, 10, 18, tzinfo=UTC)
        last = dt.datetime(2026, 11, 6, 9, 15, 36, tzinfo=UTC)
        def row(sid, ready, slot=None):
            return {
                "id": sid, "title": sid, "eligible": True,
                "status": "⏳ Ждёт часовой интервал",
                "ready_at": dt.datetime(2026, 11, 6, ready, tzinfo=UTC),
                "publish_at": slot,
                "source_path": "editorial_inbox/stories/" + sid + ".json",
                "cover_path": "editorial_inbox/covers/" + sid + ".webp",
            }
        future = row("old-but-future", 7, dt.datetime(2026, 11, 6, 13, tzinfo=UTC))
        first = row("first-ready", 9)
        second = row("second-ready", 10)
        plan = forecast_order([second, future, first], last, now=now)
        self.assertEqual([r["id"] for r, _ in plan],
                         ["first-ready", "second-ready", "old-but-future"])
        self.assertEqual([when.strftime("%H:%M") for _, when in plan],
                         ["10:22", "11:22", "13:07"])
        self.assertEqual(next_cron_tick(dt.datetime(
            2026, 11, 6, 10, 15, 36, tzinfo=UTC)).strftime("%H:%M"), "10:22")
        page = as_markdown([second, future, first], last, now=now)
        self.assertLess(page.index("first-ready"), page.index("second-ready"))
        self.assertLess(page.index("second-ready"), page.index("old-but-future"))
        self.assertIn("Не ранее 06.11.2026 15:22", page)
        self.assertIn("Прогноз — не обещание", page)

    def test_invalid_dzen_reference_is_excluded_and_explained(self):
        paths = "\n".join([
            "editorial_inbox/stories/gpt6.json",
            "editorial_inbox/covers/gpt6.webp",
            "editorial_inbox/stories/clean.json",
            "editorial_inbox/covers/clean.webp",
        ])
        bad = "6aec5fa092fe100941ed2933"
        def blob(ref, path):
            if path == "news.json":
                return "[]"
            sid = path.split("/")[-1].split(".")[0]
            return json.dumps({
                "id": sid, "title": "Article " + sid,
                "status": "editor_approved", "approved_by": "human_editor",
                "related_dzen_ids": [bad] if sid == "gpt6" else [],
            })
        with patch("scripts.render_site_publication_queue.git",
                   return_value=SimpleNamespace(stdout=paths)), \
             patch("scripts.render_site_publication_queue.safe_git_blob_at",
                   side_effect=blob), \
             patch("scripts.render_site_publication_queue.exists_at",
                   return_value=False), \
             patch("scripts.render_site_publication_queue.latest_site_first_publication",
                   return_value=None), \
             patch("scripts.render_site_publication_queue.catalog_entries",
                   return_value={}), \
             patch("scripts.render_site_publication_queue._last_change",
                   return_value=NOW - dt.timedelta(hours=2)):
            rows, last = scan_queue(now=NOW)
        got = {r["id"]: r for r in rows}
        self.assertFalse(got["gpt6"]["eligible"])
        self.assertEqual(got["gpt6"]["status"], "⛔ Заблокирована: связи с Дзеном")
        self.assertIn(bad, got["gpt6"]["block_reason"])
        self.assertTrue(got["clean"]["eligible"])
        page = as_markdown(rows, last, now=NOW)
        self.assertIn("Заблокированы:** 1", page)
        self.assertIn("Unverified Dzen article reference", page)
        self.assertEqual([r["id"] for r, _ in forecast_order(rows, last, now=NOW)],
                         ["clean"])
        self.assertLess(page.index("Article clean"), page.index("Article gpt6"))

    def test_published_rows_are_sorted_descending_by_actual_date(self):
        rows = [
            {"id": sid, "title": sid, "status": "✅ Опубликована",
             "published": True, "published_at": timestamp,
             "eligible": False, "source_path": "editorial_inbox/stories/" + sid + ".json",
             "cover_path": None}
            for sid, timestamp in (
                ("yesterday", "2026-11-05T11:00:00Z"),
                ("newest", "2026-11-06T11:00:00Z"),
                ("earliest", "2026-11-04T11:00:00Z"),
            )
        ]
        page = as_markdown(rows, None, now=NOW)
        self.assertLess(page.index("newest"), page.index("yesterday"))
        self.assertLess(page.index("yesterday"), page.index("earliest"))
        self.assertNotIn("| **1** | [newest]", page)

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
                   side_effect=lambda ref, item_path: (
                       "[]" if item_path == "news.json" else
                       '{"title":"Verified test article","source_url":"https://example.org/valid"}'
                   )), \
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
