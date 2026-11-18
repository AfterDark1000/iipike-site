import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from dzen_stage_a4_probe import Thresholds, evaluate

NOW = datetime(2026, 11, 18, 18, 30, tzinfo=UTC)
PUBLISHER = "a" * 24
THRESHOLDS = Thresholds()


def card(number, age, title="Новая нейросеть обучается на примерах", views=0, comments=0, enabled=True):
    return {
        "item_type": "native",
        "publisher_id": PUBLISHER,
        "link": f"https://dzen.ru/a/{number:016d}?tracking=discard",
        "title": title,
        "views": views,
        "publication_date": str(int((NOW - timedelta(minutes=age)).timestamp())),
        "socialInfo": {"commentCount": comments, "commentsEnabled": enabled},
    }


def snapshot(slug, cards):
    return slug, {
        "channel": {"status": "ok", "source": {"publisher_id": PUBLISHER, "title": slug,
                                               "feed_link": f"https://dzen.ru/{slug}"}},
        "items": cards,
    }, NOW


def history(views=500):
    return [card(i, 24 * 60 + i * 180, views=views if i < 5 else 50_000,
                 comments=1 if i < 3 else 0) for i in range(1, 6)]


class FirstCarriageTest(unittest.TestCase):
    def test_history_and_fresh_post_metrics_are_independent(self):
        cards = [
            card(6, 30, "ChatGPT изучает новые языки", views=0),
            card(7, 31, "Claude переводит книги", views=None, comments=3),
            card(8, 60, "OpenAI тестирует голосового помощника", views=900),
            card(9, 120, "ИИ исследует звёзды", views=20_000, comments=10),
        ]
        result = evaluate([snapshot("qualified", history() + cards)], THRESHOLDS)
        channel = result["channels"][0]["history"]
        self.assertEqual(channel["status"], "priority_b")
        self.assertEqual(channel["channel_historical_median_views"], 500)
        self.assertEqual(channel["channel_history_sample_size"], 5)
        self.assertEqual(channel["channel_history_discussion_rate"], 0.4)
        self.assertEqual([a["current_article_views"] for a in result["opportunities"]], [0, None, 900, 20_000])
        first = result["opportunities"][0]
        self.assertEqual(first["first_seen_at"], NOW.isoformat())
        self.assertEqual(first["published_at"], (NOW - timedelta(minutes=30)).isoformat())
        self.assertNotIn("?", first["url"])
        self.assertEqual(result["qualified_candidate_timing"], {
            "total": 4, "within_30_minutes": 1, "within_60_minutes": 3,
            "rate_30_minutes": 0.25, "rate_60_minutes": 0.75,
        })

    def test_article_filters_never_convert_unknown_comments_to_zero(self):
        no_date = card(12, 10)
        del no_date["publication_date"]
        no_date["creation_time"] = "10 минут назад"
        cards = [
            card(6, 120 + 1 / 60),
            card(7, 25, "Обычный электромобиль"),
            card(8, 25, comments=None),
            card(9, 25, comments=11),
            card(10, 25, enabled=False),
            card(11, -1),
            no_date,
        ]
        result = evaluate([snapshot("qualified", history() + cards)], THRESHOLDS)
        channel = result["channels"][0]
        self.assertEqual(channel["article_filters"], {
            "off_topic": 1, "unknown_comment_count": 1, "too_many_comments": 1,
            "comments_closed_or_unconfirmed": 1, "older_than_120_minutes": 6,
        })
        self.assertEqual(channel["skipped_cards"], {"future_date": 1, "missing_exact_date": 1})
        self.assertEqual(channel["all_cards"]["comments"], {"positive": 3, "zero": 8, "unknown": 1})
        self.assertEqual(result["opportunities"], [])
        self.assertIsNone(result["qualified_candidate_timing"]["rate_30_minutes"])

    def test_insufficient_and_low_activity_channels_are_kept_out_of_main_list(self):
        snapshots = [
            snapshot("unproven", history()[:4] + [card(7, 8, "Grok открывает новый анализ данных")]),
            snapshot("low", history(100) + [card(8, 15, "OpenAI проверяет качество переводов")]),
            snapshot("irregular", [card(i, 3 * 24 * 60 + 60 + i * 120, views=1000, comments=1)
                                   for i in range(1, 6)]),
        ]
        result = evaluate(snapshots, THRESHOLDS)
        self.assertEqual([ch["history"]["status"] for ch in result["channels"]],
                         ["insufficient_evidence", "low_activity", "low_activity"])
        self.assertEqual(result["opportunities"], [])
        self.assertEqual(len(result["unqualified_candidates"]), 2)

    def test_near_duplicate_prefers_article_from_qualified_channel(self):
        old = card(6, 57, "Новая нейросеть заметно ускоряет распознавание речи Python")
        newer = card(7, 8, "Нейросеть заметно ускоряет распознавание речи Python сегодня")
        result = evaluate([snapshot("unproven", [newer]), snapshot("qualified", history(1000) + [old])],
                          THRESHOLDS)
        self.assertEqual(result["duplicate_stories"], 1)
        self.assertEqual(result["opportunities"][0]["channel"], "qualified")
        self.assertEqual(result["unqualified_candidates"], [])


if __name__ == "__main__":
    unittest.main()
