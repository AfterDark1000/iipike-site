"""Offline checks for article identity, honest failures, cost limits and no posting."""
import datetime as dt
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from scripts import commenting_queue as cq

NOW = dt.datetime(2026, 11, 8, 7, tzinfo=dt.timezone.utc)
ROOT = Path(__file__).resolve().parents[1]
BODY = ("Исследователи проверили новую модель на открытых задачах. "
        "В эксперименте участвовали только заранее подготовленные примеры. ") * 5
SOURCE = {"id": "ixbt", "name": "iXBT.com", "hosts": ["www.ixbt.com"],
          "feed_url": "https://www.ixbt.com/export/news/rss.xml", "channel_url": "https://dzen.ru/ixbt.com"}
CONFIG = {"schema_version": 1, "sources": [SOURCE], "max_age_hours": 48, "max_per_run": 3, "max_per_day": 24}


def rss(title="Новая ИИ-модель прошла тест", published="Sun, 08 Nov 2026 08:40:00 +0300", url="https://www.ixbt.com/news/story.html"):
    return f"<rss><channel><item><title>{title}</title><link>{url}</link><pubDate>{published}</pubDate></item></channel></rss>"


def fetcher(url, source):
    return rss() if url == source["feed_url"] else '<article><p>' + BODY + '</p></article>'


def model(candidates, key):
    return {"comments": [{"id": c["id"], "use": True,
                          "comment": "Хотелось бы увидеть, как эта модель справится с задачами за пределами подготовленной подборки))",
                          "evidence": "В эксперименте участвовали только заранее подготовленные примеры.",
                          "reason": "Вопрос о границах проверки модели"} for c in candidates]}


class FeedTests(unittest.TestCase):
    def test_freshness_requires_known_timezone_and_no_future_dates(self):
        self.assertEqual(len(cq.feed_items(rss(), SOURCE, NOW)), 1)
        for published in ["Sun, 08 Nov 2026 18:40:00 +0300", "Sun, 01 Nov 2026 08:40:00 +0300", "2026-11-08", "unknown"]:
            self.assertEqual(cq.feed_items(rss(published=published), SOURCE, NOW), [])

    def test_relevance_does_not_match_paid_or_generic_news(self):
        for title in ["Paid subscription", "Новый автомобиль", "Скидки на процессоры"]:
            self.assertEqual(cq.feed_items(rss(title=title), SOURCE, NOW), [])
        for title in ["ИИ изменил поиск", "Claude прошёл тест", "Новая нейросеть", "AI model"]:
            self.assertEqual(len(cq.feed_items(rss(title=title), SOURCE, NOW)), 1)

    def test_url_identity_and_publisher_boundaries(self):
        for url in ["https://evil.test/story", "https://www.ixbt.com.evil.test/story", "https://x@www.ixbt.com/story", "https://www.ixbt.com:444/story", "https://login.vk.com", "https://dzen.ru/a/12345678"]:
            with self.assertRaises(ValueError): cq.allowed_url(url, SOURCE["hosts"])
        self.assertEqual(cq.feed_items(rss(url="https://evil.test/story"), SOURCE, NOW), [])
        item = cq.feed_items(rss(), SOURCE, NOW)[0]
        self.assertIsNone(item["dzen_url"])
        self.assertIsNone(item["views"])

    def test_redirect_checked_before_request_is_created(self):
        redirect = cq.PublisherRedirect(SOURCE["hosts"])
        with self.assertRaises(ValueError):
            redirect.redirect_request(None, None, 302, "", {}, "https://login.vk.com/")

    def test_login_page_not_mistaken_for_empty_news(self):
        with self.assertRaises(ValueError): cq.feed_items("<html>Log in</html>", SOURCE, NOW)
        with self.assertRaises(ValueError): cq.feed_items("<rss><channel/></rss>", SOURCE, NOW)


class ArticleTests(unittest.TestCase):
    def test_body_excludes_navigation_and_comments_outside_article(self):
        raw = '<nav>ПОДМЕНА</nav><article><h1>ИИ</h1><p>' + BODY + '</p><aside>РЕКЛАМА</aside></article><div>КОММЕНТАРИИ</div>'
        text, mirror = cq.article_text(raw)
        self.assertIn("Исследователи", text)
        for term in ["ПОДМЕНА", "РЕКЛАМА", "КОММЕНТАРИИ"]: self.assertNotIn(term, text)
        self.assertIsNone(mirror)

    def test_jsonld_article_and_explicit_mirror(self):
        data = {"@graph": [{"@type": "NewsArticle", "articleBody": BODY,
                            "sameAs": "https://dzen.ru/a/abcdefgh123"}]}
        raw = '<script type="application/ld+json">' + json.dumps(data) + '</script>'
        self.assertEqual(cq.article_text(raw), (cq.normalized(BODY), "https://dzen.ru/a/abcdefgh123"))

    def test_dzen_links_in_navigation_never_become_article_mirrors(self):
        raw = '<a href="https://dzen.ru/a/unrelated12">Другой материал</a><article>' + BODY + '</article>'
        self.assertIsNone(cq.article_text(raw)[1])

    def test_in_article_carousels_and_related_news_are_excluded(self):
        raw = '<div itemprop="articleBody"><div class="js-mediator-article"><p>' + BODY + '</p><div class="slider-container">ЧУЖАЯ НОВОСТЬ</div></div><div class="ps-promo">РЕКЛАМА</div><div class="relatedbox">ЧУЖАЯ СТАТЬЯ</div></div>'
        text, _ = cq.article_text(raw)
        self.assertEqual(text, cq.normalized(BODY))

    def test_refuses_headline_only_unstructured_and_truncated_inputs(self):
        for raw in ['<h1>ИИ</h1>', '<div>' + BODY + '</div>', '<article>' + 'x' * 24001 + '</article>']:
            with self.assertRaises(ValueError): cq.article_text(raw)


class QueueTests(unittest.TestCase):
    def build(self, previous=None, **kwargs):
        return cq.build_queue(CONFIG, previous or {}, NOW, fetcher=fetcher, model=model, api_key="test-placeholder", **kwargs)

    def test_success_keeps_only_metadata_and_comment_never_full_article(self):
        queue = self.build()
        self.assertEqual(queue["sources"][0]["status"], "ok")
        self.assertEqual(queue["items"][0]["status"], "draft_ready")
        self.assertEqual(queue["items"][0]["link_status"], "dzen_link_missing")
        self.assertNotIn("article_text", json.dumps(queue))
        self.assertEqual(queue["usage"]["attempted"], 1)

    def test_repeat_run_keeps_draft_and_does_not_call_model(self):
        queue = self.build()
        def no_call(*args): self.fail("Duplicate model call")
        repeated = cq.build_queue(CONFIG, queue, NOW + dt.timedelta(minutes=30), fetcher=fetcher, model=no_call, api_key="x")
        self.assertEqual(repeated["items"][0]["first_seen_at"], queue["items"][0]["first_seen_at"])
        self.assertEqual(repeated["usage"]["attempted"], 1)

    def test_all_sources_fail_preserves_previous_drafts_and_health(self):
        queue = self.build()
        def unavailable(*args): raise TimeoutError()
        result = cq.build_queue(CONFIG, queue, NOW + dt.timedelta(hours=1), fetcher=unavailable, model=model, api_key="x")
        self.assertEqual(result["sources"][0]["status"], "error")
        self.assertIsNone(result["sources"][0]["fresh_matches"])
        self.assertEqual(result["sources"][0]["last_success_at"], cq.stamp(NOW))
        self.assertEqual(result["items"][0]["comment"], queue["items"][0]["comment"])

    def test_unreadable_article_never_reaches_model(self):
        def source(url, config): return rss() if url == config["feed_url"] else "<html>Access denied</html>"
        def no_call(*args): self.fail("Unreadable article passed to model")
        result = cq.build_queue(CONFIG, {}, NOW, fetcher=source, model=no_call, api_key="x")
        self.assertEqual(result["items"][0]["status"], "read_error")
        self.assertEqual(result["generator"]["status"], "read_error")

    def test_invalid_generated_evidence_and_ads_rejected(self):
        candidates = [{"id": "x", "article_text": BODY}]
        base = model(candidates, "x")
        for patch in [{"evidence": "Этого в статье вообще не было"}, {"comment": "Коротко"},
                      {"comment": "Подписывайтесь на наш замечательный канал о нейросетях и технологиях!"},
                      {"comment": "Я пробовал эту замечательную нейросеть, она прекрасно работает."}]:
            row = dict(base["comments"][0], **patch)
            checked = cq.validate_comments({"comments": [row]}, candidates)["x"]
            self.assertNotEqual(checked["status"], "draft_ready")
            self.assertEqual(checked["comment"], "")
            self.assertEqual(checked["fact_review"], "rejected")

    def test_model_may_skip_uninteresting_article(self):
        result = cq.validate_comments({"comments": [{"id": "x", "use": False, "comment": "", "reason": "Нет содержательного захода"}]}, [{"id": "x", "article_text": BODY}])
        self.assertEqual(result["x"]["status"], "skipped_by_editor")

    def test_fact_review_discards_wrong_claim_without_publishing_it(self):
        candidates = [{"id": "x", "article_text": BODY}]
        proposed = model(candidates, "x")
        reviewed = cq.apply_review(proposed, {"checks": [{"id": "x", "ok": False, "reason": "Перепутана цель раунда и первый транш"}]})
        result = cq.validate_comments(reviewed, candidates)
        self.assertEqual(result["x"]["comment"], "")
        self.assertEqual(result["x"]["fact_review"], "rejected")
        self.assertNotEqual(result["x"]["status"], "draft_ready")

    def test_incomplete_or_misidentified_fact_review_is_rejected(self):
        for review in [{"checks": []}, {"checks": [{"id": "y", "ok": True}]},
                       {"checks": [{"id": "x", "ok": "true"}]}]:
            with self.assertRaises(ValueError): cq.apply_review(model([{"id": "x"}], "x"), review)

    def test_production_model_always_runs_independent_review(self):
        candidates = [{"id": "x", "article_text": BODY}]
        with patch.object(cq, "model_request", side_effect=[model(candidates, "x"),
                          {"checks": [{"id": "x", "ok": True, "reason": "Факты совпадают"}]}]) as request:
            response = cq.ask_model(candidates, "test-placeholder")
        self.assertEqual(request.call_count, 2)
        self.assertEqual(response["comments"][0]["fact_review"], "passed")

    def test_failed_reviewer_never_falls_back_to_unreviewed_draft(self):
        candidates = [{"id": "x", "article_text": BODY}]
        with patch.object(cq, "model_request", side_effect=[model(candidates, "x"), RuntimeError("HTTP 429")]):
            with self.assertRaises(RuntimeError): cq.ask_model(candidates, "test-placeholder")

    def test_one_bad_comment_does_not_discard_other_articles(self):
        candidates = [{"id": "x", "article_text": BODY}, {"id": "y", "article_text": BODY}]
        proposed = model(candidates, "x")
        proposed["comments"][1]["evidence"] = "Выдуманная выдержка из статьи"
        with patch.object(cq, "model_request", side_effect=[proposed,
                          {"checks": [{"id": "x", "ok": True, "reason": "Совпадает"}]}]) as request:
            response = cq.ask_model(candidates, "test-placeholder")
        result = cq.validate_comments(response, candidates)
        self.assertEqual(result["x"]["status"], "draft_ready")
        self.assertNotEqual(result["y"]["status"], "draft_ready")
        self.assertEqual(result["y"]["comment"], "")
        self.assertEqual(request.call_count, 2)

    def test_missing_key_no_paid_fallback_and_no_fake_ready_comment(self):
        def no_call(*args): self.fail("Model must not be called")
        result = cq.build_queue(CONFIG, {}, NOW, fetcher=fetcher, model=no_call)
        self.assertEqual(result["generator"]["status"], "missing_credentials")
        self.assertEqual(result["items"][0]["status"], "pending")

    def test_daily_limit_and_failed_calls_are_counted_with_cooldown(self):
        def unavailable(*args): raise RuntimeError("Модель вернула HTTP 429")
        first = cq.build_queue(CONFIG, {}, NOW, fetcher=fetcher, model=unavailable, api_key="x")
        self.assertEqual(first["items"][0]["status"], "generation_error")
        self.assertEqual(first["usage"]["attempted"], 1)
        second = cq.build_queue(CONFIG, first, NOW + dt.timedelta(minutes=30), fetcher=fetcher, model=unavailable, api_key="x")
        self.assertEqual(second["usage"]["attempted"], 1)
        second["usage"]["attempted"] = 24
        third = cq.build_queue(CONFIG, second, NOW + dt.timedelta(hours=7), fetcher=fetcher, model=unavailable, api_key="x")
        self.assertEqual(third["generator"]["status"], "daily_limit")

    def test_configuration_does_not_allow_arbitrary_domains(self):
        config = cq.load_config(ROOT / "data/commenting_sources.json")
        self.assertEqual(len(config["sources"]), 4)
        self.assertTrue(all(s["channel_reference"].startswith("https://") for s in config["sources"]))

    def test_operator_page_does_not_pollute_reader_analytics(self):
        page = (ROOT / "admin/commenting/index.html").read_text()
        self.assertNotIn("social-footer.js", page)
        self.assertNotIn("mc.yandex.ru", page)
        self.assertIn('noindex,nofollow,noarchive', page)


if __name__ == "__main__": unittest.main()
