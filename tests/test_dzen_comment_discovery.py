import datetime as dt
import unittest

from scripts import dzen_comment_discovery as d

CONFIG = {"max_age_hours": 72, "per_channel_limit": 2, "max_items": 20}


def entry(url, published="2026-11-18 12:00:00.000000", title="Нейросеть научилась обсуждать новые статьи"):
    return {"canonicalUrl": url, "url": "https://dzen.ru/id/5e428f13bf8d3263221b5924",
            "channelTitle": "Маленький канал", "title": title,
            "datePublishAt": {"date": published, "timezone": "Europe/Moscow"},
            "countViews": 2500, "countComments": 12, "subscribers": 700}


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 18, 14, 0, tzinfo=dt.timezone.utc)

    def test_only_direct_article_urls(self):
        valid = "https://dzen.ru/a/abcdef0123456789"
        legacy = "https://dzen.ru/media/id/" + "a" * 24 + "/" + "b" * 24
        self.assertEqual(d.direct_article_url(valid + "?utm_source=foo"), valid)
        self.assertEqual(d.direct_article_url(legacy), legacy)
        for url in ["https://dzen.ru/search?query=ChatGPT",
                    "https://dzen.ru/id/5e428f13bf8d3263221b5924",
                    "https://dzen.ru/a/short",
                    "https://evil.dzen.ru/a/abcdef0123456789",
                    "http://dzen.ru/a/abcdef0123456789",
                    "https://dzen.ru.evil.com/a/abcdef0123456789"]:
            self.assertIsNone(d.direct_article_url(url), url)

    def test_old_articles_not_reintroduced_by_ranking(self):
        fresh = entry("https://dzen.ru/a/abcdef0123456789")
        old = entry("https://dzen.ru/a/abcdef0123456790", published="2024-11-18 12:00:00")
        result = d.compile_results([old, fresh], [], CONFIG, now=self.now)
        self.assertEqual(len(result["ready"]), 1)
        self.assertEqual(result["ready"][0]["dzen_url"], fresh["canonicalUrl"])
        self.assertEqual(result["stats"]["outdated_or_future"], 1)

    def test_brave_age_does_not_become_publication_date(self):
        brave = {"url": "https://dzen.ru/a/abcdef0123456789",
                 "title": "ChatGPT и искусственный интеллект",
                 "page_age": "2026-11-18T12:00:00"}
        result = d.compile_results([], [brave], CONFIG, now=self.now)
        self.assertEqual(result["ready"], [])
        self.assertEqual(len(result["needs_publication_date"]), 1)
        self.assertEqual(result["needs_publication_date"][0]["date_status"], "unknown")

    def test_provider_date_wins_duplicate(self):
        link = "https://dzen.ru/a/abcdef0123456789"
        brave = {"url": link, "title": "Нейросеть стала лучше", "page_age": "2026-11-18"}
        result = d.compile_results([entry(link)], [brave], CONFIG, now=self.now)
        self.assertEqual(len(result["ready"]), 1)
        self.assertEqual(len(result["needs_publication_date"]), 0)
        self.assertEqual(result["ready"][0]["indexed_at"], "2026-11-18")

    def test_small_channels_preferred_but_big_not_excluded(self):
        tiny = entry("https://dzen.ru/a/abcdef0123456789")
        huge = entry("https://dzen.ru/a/abcdef0123456790")
        huge["channelTitle"] = "Крупное медиа"
        huge["url"] = "https://dzen.ru/id/" + "b" * 24
        huge["subscribers"] = 100000
        huge["countViews"] = 100
        huge["countComments"] = 1
        result = d.compile_results([huge, tiny], [], CONFIG, now=self.now)
        self.assertEqual(len(result["ready"]), 2)
        self.assertEqual(result["ready"][0]["channel_name"], "Маленький канал")

    def test_cap_one_channel_without_blocking_others(self):
        config = dict(CONFIG, per_channel_limit=1)
        data = [entry("https://dzen.ru/a/abcdef0123456789"),
                entry("https://dzen.ru/a/abcdef0123456790"),
                entry("https://dzen.ru/a/abcdef0123456791")]
        other = entry("https://dzen.ru/a/abcdef0123456792")
        other["url"] = "https://dzen.ru/id/" + "c" * 24
        other["channelTitle"] = "Ещё один канал"
        result = d.compile_results(data + [other], [], config, now=self.now)
        self.assertEqual(len(result["ready"]), 2)
        self.assertEqual(result["stats"]["channel_cap"], 2)

    def test_missing_dates_and_non_ai_are_not_ready(self):
        bad = entry("https://dzen.ru/a/abcdef0123456789", title="Печём яблочный пирог дома быстро")
        unknown = entry("https://dzen.ru/a/abcdef0123456790")
        unknown.pop("datePublishAt")
        result = d.compile_results([bad, unknown], [], CONFIG, now=self.now)
        self.assertEqual(len(result["ready"]), 0)
        self.assertEqual(len(result["needs_publication_date"]), 1)

    def test_future_publication_is_rejected(self):
        future = entry("https://dzen.ru/a/abcdef0123456789", published="2026-12-01 12:00:00")
        result = d.compile_results([future], [], CONFIG, now=self.now)
        self.assertEqual(len(result["ready"]), 0)
        self.assertEqual(result["stats"]["outdated_or_future"], 1)


if __name__ == "__main__":
    unittest.main()
