import datetime as dt
from email.message import Message
from io import BytesIO
import json
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


def media_fetch(url, _source):
    if url != RSS["feed_url"]:
        return f"<article><p>{BODY}</p></article>"
    stories = "".join(f"<item><title>Новая модель ИИ {i}</title><link>https://www.ixbt.com/{i}.html</link>"
                      f"<pubDate>{ARTICLE['published_at']}</pubDate></item>" for i in range(3))
    return f"<rss><channel>{stories}</channel></rss>"


def prepare(reader, *, allowed=True, previous=None, media=None, now=NOW):
    return first_car.prepare({"articles": [ARTICLE]}, previous or {}, media or {}, CONFIG, now,
                             allowed=allowed, api_key="test-key", reader=reader)


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

    def test_dzen_shares_existing_batch_quota_and_fact_review_with_publishers(self):
        drafts, candidate = prepare(Mock(return_value=BODY))
        proposed, checked = [], []

        def generate(payload, _key):
            prompt = payload["contents"][0]["parts"][0]["text"]
            rows = json_rows(prompt)
            if "строгий фактчекер" in prompt:
                checked.extend(rows)
                return {"checks": [{"id": row["id"], "ok": True} for row in rows]}
            proposed.extend(rows)
            return {"comments": [{"id": row["id"], "use": True, "evidence": EVIDENCE,
                                  "comment": "Интересно, что покажет та же модель за пределами подготовленной подборки."}
                                 for row in rows]}

        with patch.object(cq, "model_request", side_effect=generate) as request:
            media = cq.build_queue(CONFIG, {}, NOW, fetcher=media_fetch, api_key="test-key", first_car=candidate)
        self.assertEqual(request.call_count, 2)  # One shared generation and one shared fact-check.
        self.assertEqual(len(proposed), 3)
        self.assertEqual(len(checked), 3)
        self.assertEqual(media["usage"]["attempted"], 3)
        self.assertEqual(sum(row["status"] == "draft_ready" for row in media["items"]), 2)
        self.assertNotIn(URL, [row["source_url"] for row in media["items"]])
        self.assertEqual(drafts["items"][0]["fact_review"], "passed")
        self.assertTrue(drafts["items"][0]["comment"])
        self.assertNotIn("article_text", drafts["items"][0])

    def test_last_daily_slot_stays_available_to_publisher(self):
        previous = {"schema_version": 1, "usage": {"date": "2026-11-20", "attempted": 23}}
        drafts, candidate = prepare(Mock(return_value=BODY), media=previous)
        model = Mock(side_effect=RuntimeError("Модель вернула HTTP 503"))
        media = cq.build_queue(CONFIG, previous, NOW, fetcher=media_fetch, model=model, api_key="test-key", first_car=candidate)
        self.assertEqual(media["usage"]["attempted"], 24)
        self.assertEqual(len(model.call_args.args[0]), 1)
        self.assertEqual(drafts["items"][0]["status"], "pending")
        reader = Mock(return_value=BODY)
        _, candidate = prepare(reader, previous=drafts, media=media)
        self.assertIsNone(candidate)
        reader.assert_not_called()

    def test_503_counts_toward_quota_and_dzen_retry_is_deferred(self):
        drafts, candidate = prepare(Mock(return_value=BODY))
        fetch = lambda _url, _source: "<rss><channel/></rss>"
        model = Mock(side_effect=RuntimeError("Модель вернула HTTP 503"))
        media = cq.build_queue(CONFIG, {}, NOW, fetcher=fetch, model=model, api_key="test-key", first_car=candidate)
        self.assertEqual(media["usage"]["attempted"], 1)
        self.assertEqual(drafts["items"][0]["status"], "generation_error")
        self.assertNotIn("comment", drafts["items"][0])
        reader = Mock(return_value=BODY)
        _, candidate = prepare(reader, previous=drafts, media=media, now=NOW + dt.timedelta(hours=1))
        self.assertIsNone(candidate)
        reader.assert_not_called()
        model.assert_called_once()


def json_rows(prompt):
    return json.loads(prompt.rsplit("Данные: " if "строгий фактчекер" in prompt else "Данные статей: ", 1)[-1])
