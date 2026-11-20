import datetime as dt
from email.message import Message
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import commenting_queue as cq
from scripts import first_car_commenting as first_car


NOW = dt.datetime(2026, 11, 20, 5, 30, tzinfo=dt.timezone.utc)
URL = "https://dzen.ru/a/first-car-fixture"
ARTICLE = {"url": URL, "source": "dzen_launcher_more", "title": "Новая модель ИИ",
           "published_at": cq.stamp(NOW - dt.timedelta(minutes=10))}
EVIDENCE = "Модель проверяли на заранее подготовленных примерах."
BODY = (EVIDENCE + " Авторы сравнили ответы моделей на одних и тех же задачах. ") * 6
RSS = {"id": "ixbt", "name": "iXBT", "feed_url": "https://www.ixbt.com/feed.xml",
       "hosts": ["www.ixbt.com"], "channel_url": "https://dzen.ru/ixbt.com"}
CONFIG = {"sources": [RSS], "max_per_run": 3, "max_per_day": 24, "max_age_hours": 48}


def media_fetch(url, _source, count=3):
    if url != RSS["feed_url"]:
        return f"<article><p>{BODY}</p></article>"
    stories = "".join(f"<item><title>Новая модель ИИ {i}</title><link>https://www.ixbt.com/{i}.html</link>"
                      f"<pubDate>{ARTICLE['published_at']}</pubDate></item>" for i in range(count))
    return f"<rss><channel>{stories}</channel></rss>"


def prepare(reader, *, allowed=True, previous=None, media=None, now=NOW, submitted=None):
    return first_car.prepare({"articles": [ARTICLE]}, previous or {}, media or {}, CONFIG, now,
                             allowed=allowed, api_key="test-key", reader=reader, submitted=submitted)


class FirstCarCommentingTests(unittest.TestCase):
    def test_read_public_body_requires_matching_url_and_full_text(self):
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"

        def opener(body, canonical=URL):
            response = BytesIO(f'<link rel="canonical" href="{canonical}"><article>{body}</article>'.encode())
            response.headers = headers
            response.geturl = lambda: URL
            return Mock(open=Mock(return_value=response))

        public = opener(BODY)
        self.assertIn(EVIDENCE, first_car.read_dzen_text(URL, opener=public))
        request = public.open.call_args.args[0]
        self.assertIsNone(request.get_header("Cookie"))
        with self.assertRaises(ValueError):
            first_car.read_dzen_text(URL, opener=opener("Только заголовок"))
        with self.assertRaises(ValueError):
            first_car.read_dzen_text(URL, opener=opener(BODY, "https://dzen.ru/a/another-page"))

    def test_no_text_approval_or_access_refusal_never_supplies_model_context(self):
        reader = Mock(return_value=BODY)
        disabled, candidate = prepare(reader, allowed=False)
        reader.assert_not_called()
        self.assertIsNone(candidate)
        self.assertEqual(disabled["items"][0]["status"], "needs_text")

        short, candidate = prepare(Mock(return_value="Заголовок"))
        self.assertIsNone(candidate)
        self.assertEqual(short["items"][0]["status"], "read_error")
        denied, candidate = prepare(Mock(side_effect=first_car.TextAccessStopped("Dzen article HTTP 403")))
        self.assertIsNone(candidate)
        self.assertTrue(denied["text_blocked"])
        _, candidate = prepare(reader, previous=denied)
        reader.assert_not_called()
        self.assertIsNone(candidate)

    def test_dzen_uses_spare_quota_and_fact_check_without_entering_publisher_batch(self):
        reader = Mock()
        owner_text = BODY + "Отдельная проверочная пометка для текста Дзена."
        drafts, candidate = prepare(reader, allowed=False, submitted={URL: owner_text})
        calls = []

        def generate(payload, _key):
            prompt = payload["contents"][0]["parts"][0]["text"]
            rows = json_rows(prompt)
            calls.append(rows)
            if "строгий фактчекер" in prompt:
                return {"checks": [{"id": row["id"], "ok": True} for row in rows]}
            return {"comments": [{"id": row["id"], "use": True, "evidence": EVIDENCE,
                                  "comment": "Интересно, что покажет та же модель за пределами подготовленной подборки."}
                                 for row in rows]}

        with patch.object(cq, "model_request", side_effect=generate) as request:
            media = cq.build_queue(CONFIG, {}, NOW, fetcher=lambda url, source: media_fetch(url, source, 2),
                                   api_key="test-key")
            first_car.generate(candidate, media, {}, CONFIG, NOW, "test-key")
        self.assertEqual(request.call_count, 4)  # Two publisher calls, then two Dzen calls.
        reader.assert_not_called()
        self.assertEqual([len(batch) for batch in calls], [2, 2, 1, 1])
        self.assertFalse(any(owner_text in row["article_text"] for batch in calls[:2] for row in batch))
        self.assertTrue(all(batch[0]["article_text"] == owner_text for batch in calls[2:]))
        self.assertEqual(media["usage"]["attempted"], 3)
        self.assertEqual(sum(row["status"] == "draft_ready" for row in media["items"]), 2)
        self.assertNotIn(URL, [row["source_url"] for row in media["items"]])
        self.assertEqual(drafts["items"][0]["fact_review"], "passed")
        self.assertTrue(drafts["items"][0]["comment"])
        self.assertNotIn("article_text", drafts["items"][0])
        _, candidate = prepare(reader, allowed=False, previous=drafts, submitted={URL: BODY})
        self.assertIsNone(candidate)
        reader.assert_not_called()

    def test_submitted_context_matches_exact_discovery_and_expires_or_recovers_from_blocked_read(self):
        reader = Mock(side_effect=first_car.TextAccessStopped("Dzen article HTTP 403"))
        drafts, _ = prepare(reader)
        failed = drafts["items"][0]
        self.assertEqual(failed["status"], "read_error")
        for text in ({URL: "Заголовок"}, {"https://dzen.ru/a/another-page": BODY}):
            retained, candidate = prepare(reader, allowed=False, previous=drafts, submitted=text)
            self.assertIsNone(candidate)
            self.assertEqual(retained["items"][0]["status"], "read_error")
        recovered, candidate = prepare(reader, allowed=False, previous=drafts, submitted={URL: BODY})
        self.assertEqual(candidate["article_text"], BODY.strip())
        self.assertEqual(recovered["items"][0]["attempts"], 0)
        self.assertEqual(recovered["items"][0]["status"], "pending")
        expired, candidate = prepare(reader, allowed=False, submitted={URL: BODY}, now=NOW + dt.timedelta(hours=24))
        self.assertIsNone(candidate)
        self.assertFalse(expired["items"])
        reader.assert_called_once()

    def test_dzen_fails_closed_if_model_fact_check_rejects_draft(self):
        drafts, candidate = prepare(Mock(), allowed=False, submitted={URL: BODY})

        def generate(payload, _key):
            prompt = payload["contents"][0]["parts"][0]["text"]
            if "строгий фактчекер" in prompt:
                return {"checks": [{"id": candidate["item"]["id"], "ok": False}]}
            return {"comments": [{"id": candidate["item"]["id"], "use": True, "evidence": EVIDENCE,
                                  "comment": "Эксперимент точно доказал, что все другие модели проиграли."}]}

        with patch.object(cq, "model_request", side_effect=generate) as request:
            media = cq.build_queue(CONFIG, {}, NOW, fetcher=lambda *args: "<rss><channel/></rss>", api_key="test-key")
            first_car.generate(candidate, media, {}, CONFIG, NOW, "test-key")
        self.assertEqual(request.call_count, 2)
        self.assertEqual(drafts["items"][0]["status"], "skipped_by_editor")
        self.assertEqual(drafts["items"][0]["comment"], "")
        _, candidate = prepare(Mock(), allowed=False, previous=drafts, submitted={URL: BODY})
        self.assertIsNone(candidate)

    def test_last_daily_slot_stays_available_to_publisher(self):
        previous = {"schema_version": 1, "usage": {"date": "2026-11-20", "attempted": 23}}
        drafts, candidate = prepare(Mock(return_value=BODY), media=previous)
        model = Mock(side_effect=RuntimeError("Модель вернула HTTP 503"))
        media = cq.build_queue(CONFIG, previous, NOW, fetcher=media_fetch, model=model, api_key="test-key")
        first_car.generate(candidate, media, previous, CONFIG, NOW, "test-key", model=model)
        self.assertEqual(media["usage"]["attempted"], 24)
        model.assert_called_once()
        self.assertEqual(len(model.call_args.args[0]), 1)
        self.assertEqual(drafts["items"][0]["status"], "pending")
        reader = Mock(return_value=BODY)
        _, candidate = prepare(reader, previous=drafts, media=media)
        self.assertIsNone(candidate)
        reader.assert_not_called()

    def test_503_counts_toward_quota_and_dzen_retry_is_deferred(self):
        drafts, candidate = prepare(Mock(return_value=BODY))
        fetch = lambda _url, _source: "<rss><channel/></rss>"
        model = Mock(side_effect=RuntimeError("Модель вернула HTTP 503 " + BODY + " test-key"))
        media = cq.build_queue(CONFIG, {}, NOW, fetcher=fetch, model=model, api_key="test-key")
        first_car.generate(candidate, media, {}, CONFIG, NOW, "test-key", model=model)
        self.assertEqual(media["usage"]["attempted"], 1)
        self.assertEqual(drafts["items"][0]["status"], "generation_error")
        self.assertFalse(drafts["items"][0]["comment"])
        self.assertEqual(media["generator"]["status"], "idle")
        self.assertNotIn(BODY, json.dumps(media, ensure_ascii=False))
        self.assertNotIn("test-key", json.dumps(drafts, ensure_ascii=False))
        reader = Mock(return_value=BODY)
        _, candidate = prepare(reader, previous=drafts, media=media, now=NOW + dt.timedelta(hours=1))
        self.assertIsNone(candidate)
        reader.assert_not_called()
        model.assert_called_once()

    def test_actual_draft_file_uses_safe_fields_and_rejects_model_text_echo(self):
        secret = "BEFORE-TEST-ONLY-api-key"
        for proposed in (
            BODY.strip()[:180], "Вот какой ключ неожиданно вернула модель " + secret,
            "Интересно, как изменятся ответы моделей на другой выборке данных.",
        ):
            with self.subTest(comment=proposed), TemporaryDirectory() as directory:
                target = Path(directory)
                args = SimpleNamespace(discovery=target / "discovery.json", drafts_state=target / "old.json",
                                       drafts_output=target / "drafts.json", submitted_text=target / "private.json")
                args.discovery.write_text(json.dumps({"articles": [ARTICLE]}))
                args.drafts_state.write_text("{}")
                args.submitted_text.write_text(json.dumps({URL: BODY}))
                media = cq.build_queue(CONFIG, {}, NOW, fetcher=lambda *args: "<rss><channel/></rss>", api_key=secret)

                def model(rows, _key):
                    return {"comments": [{"id": rows[0]["id"], "use": True, "evidence": EVIDENCE,
                                          "comment": proposed, "reason": BODY, "fact_review": "passed"}]}

                with patch.object(cq, "ask_model", side_effect=model), patch.dict("os.environ", {"FIRST_CAR_ARTICLE_TEXT": ""}):
                    first_car.run_optional_dzen(args, CONFIG, {}, media, NOW, secret)
                public = args.drafts_output.read_text()
                self.assertNotIn(BODY.strip(), public)
                self.assertNotIn(secret, public)
                row = json.loads(public)["items"][0]
                self.assertNotIn("reason", row)
                if proposed in (BODY.strip()[:180], "Вот какой ключ неожиданно вернула модель " + secret):
                    self.assertEqual(row["status"], "skipped_by_editor")
                    self.assertNotIn("comment", row)
                else:
                    self.assertEqual(row["status"], "draft_ready")
                    self.assertEqual(row["comment"], proposed)

    def test_failed_or_missing_optional_input_still_writes_identical_publisher_queue(self):
        media = {"schema_version": 1, "generator": {"status": "ok"}, "items": [{"comment": "Комментарий СМИ"}]}
        with TemporaryDirectory() as directory, patch.object(cq, "build_queue", return_value=media) as build:
            base = Path(directory)
            state = base / "state.json"
            state.write_text("{}")
            args = ["first_car_commenting", "--state", str(state), "--output", str(base / "out.json"),
                    "--discovery", str(base / "missing.json"), "--drafts-state", str(base / "old.json"),
                    "--drafts-output", str(base / "drafts.json")]
            with patch("sys.argv", args), patch("builtins.print") as output:
                first_car.main()
            self.assertEqual(json.loads((base / "out.json").read_text()), media)
            self.assertFalse((base / "drafts.json").exists())
            build.assert_called_once()
            output.assert_called_once_with("First Car draft preparation unavailable")

    def test_empty_text_or_no_spare_capacity_does_not_change_publisher_result(self):
        def publisher_model(rows, _key):
            return {"comments": [{"id": row["id"], "use": True, "evidence": EVIDENCE,
                                  "comment": "Любопытно, получится ли повторить этот результат за пределами набора."}
                                 for row in rows]}

        with TemporaryDirectory() as directory:
            target = Path(directory)
            args = SimpleNamespace(discovery=target / "discovery.json", drafts_state=target / "old.json",
                                   drafts_output=target / "drafts.json", submitted_text=target / "private.json")
            args.discovery.write_text(json.dumps({"articles": [ARTICLE]}))
            args.drafts_state.write_text("{}")
            model = Mock(side_effect=publisher_model)
            media = cq.build_queue(CONFIG, {}, NOW, fetcher=media_fetch, model=model, api_key="test-key")
            baseline = json.dumps(media)
            model.assert_called_once()
            self.assertEqual(sum(row["status"] == "draft_ready" for row in media["items"]), 3)
            with patch.object(cq, "ask_model") as optional, patch.dict("os.environ", {"FIRST_CAR_ARTICLE_TEXT": ""}):
                first_car.run_optional_dzen(args, CONFIG, {}, media, NOW, "test-key")
                self.assertEqual(json.loads(args.drafts_output.read_text())["items"][0]["status"], "needs_text")
                args.submitted_text.write_text(json.dumps({URL: BODY}))
                first_car.run_optional_dzen(args, CONFIG, {}, media, NOW, "test-key")
                self.assertEqual(json.loads(args.drafts_output.read_text())["items"][0]["status"], "pending")
                optional.assert_not_called()
            self.assertEqual(json.dumps(media), baseline)


def json_rows(prompt):
    return json.loads(prompt.rsplit("Данные: " if "строгий фактчекер" in prompt else "Данные статей: ", 1)[-1])
