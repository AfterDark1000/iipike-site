"""Regression tests for the site-only related card and intact Dzen Markdown."""
import copy
import unittest

from scripts.site_related_cards import (
    select_site_card, remove_duplicate_related_ids, _related_fallback,
)
from scripts.site_rich_text import render_blocks
from scripts.publish_approved_article import render_article

TARGET_ID = "censys-artex-exposed-servers-20261105"
TARGET = {
    "id": TARGET_ID,
    "url": "articles/" + TARGET_ID + "/",
    "title": "Censys нашла 1465 серверов с ИИ-инструментом ARTEX",
    "summary": "Расследование обнаружило открытые консоли ARTEX.",
    "rubric": "skynet",
    "published": "2026-11-07",
    "cover": "assets/editorial/censys-artex-exposed-servers-20261105.webp",
    "dzen_id": "6aef173f8c4f2d1ca599743b",
    "dzen_url": "https://dzen.ru/a/au8XP4xPLRylmXQ7",
    "topics": ["cybersecurity", "agents"],
}
OTHER = {
    "id": "another-article",
    "url": "articles/another-article/",
    "title": "Обычная новость о кибербезопасности",
    "summary": "Без редкого названия ARTEX.",
    "rubric": "news",
    "published": "2026-11-04",
    "cover": "assets/editorial/another.webp",
    "topics": ["cybersecurity", "agents"],
}
CURRENT = {
    "slug": "sample-news",
    "title": "Стамос о безопасности ИИ",
    "summary": "Рассуждения об атаках.",
    "rubric": "quotes",
    "source_url": "https://example.org/source",
    "source_title": "Проверенный первоисточник",
    "cover": "assets/editorial/sample.webp",
    "published": "2026-11-10",
    "published_at_utc": "2026-11-10T09:15:00Z",
    "topics": ["cybersecurity", "agents"],
    "related_dzen_ids": [],
}
URL = "https://dzen.ru/a/au8XP4xPLRylmXQ7"


class RelatedCardTests(unittest.TestCase):
    def setUp(self):
        self.data = copy.deepcopy(CURRENT)
        self.records = [copy.deepcopy(TARGET), copy.deepcopy(OTHER)]
        self.blocks = [
            {"type": "lead", "text": "Эксперт рассказал о новых возможностях ИИ-агентов."},
            {"type": "p", "text": "Изменения затронули расследования кибератак."},
            {"type": "p", "text": "Инструмент ARTEX фигурировал в [расследовании](%s), продолжавшемся несколько дней." % URL},
            {"type": "p", "text": "Исследователи рекомендуют оценивать последствия."},
        ]
        self.site_links = {URL: "https://iipike.ru/" + TARGET["url"]}

    def test_inline_card_drops_site_anchor_only_and_keeps_dzen_source_intact(self):
        original_blocks = copy.deepcopy(self.blocks)
        original_markdown = "\n\n".join(b["text"] for b in self.blocks)
        site_blocks, insertions, row = select_site_card(
            self.data, self.blocks, self.records, self.site_links)
        self.assertEqual(row["id"], TARGET_ID)
        self.assertEqual(self.blocks, original_blocks)
        self.assertEqual(original_markdown, "\n\n".join(b["text"] for b in original_blocks))
        self.assertIn("[расследовании](" + URL + ")", self.blocks[2]["text"])
        self.assertIn("ARTEX фигурировал в расследовании,", site_blocks[2]["text"])
        self.assertNotIn("[расследовании]", site_blocks[2]["text"])
        page = render_blocks(site_blocks, site_links=self.site_links, after_blocks=insertions)
        self.assertEqual(page.count('class="editorial-related-card"'), 1)
        self.assertEqual(page.count('href="https://iipike.ru/articles/' + TARGET_ID + '/"'), 1)
        self.assertNotIn('class="editorial-inline-link"', page)
        self.assertNotIn("По теме · ХПИИ", page)
        self.assertLess(page.index("ARTEX фигурировал"), page.index('class="editorial-related-card"'))
        self.assertLess(page.index('class="editorial-related-card"'), page.index("Исследователи рекомендуют"))

    def test_site_html_and_editor_markdown_remain_separate(self):
        self.data["paragraphs"] = copy.deepcopy(self.blocks)
        self.data["article_markdown"] = (
            "Эксперт рассказал о новых возможностях ИИ-агентов.\n\n"
            "Изменения затронули расследования кибератак.\n\n"
            "Инструмент ARTEX фигурировал в [расследовании](" + URL + "), продолжавшемся несколько дней.\n\n"
            "Исследователи рекомендуют оценивать последствия."
        )
        before = copy.deepcopy(self.data)
        html = render_article(self.data, self.records, {})
        self.assertIn('class="editorial-related-card"', html)
        self.assertIn("ARTEX фигурировал в расследовании,", html)
        self.assertNotIn('[расследовании]', html)
        self.assertNotIn('href="' + URL + '"', html)
        self.assertEqual(self.data, before)
        self.assertIn('[расследовании](' + URL + ')', self.data["article_markdown"])

    def test_duplicate_bottom_link_is_suppressed_only_for_same_target(self):
        id_a = TARGET["dzen_id"]
        id_b = "0123456789abcdef01234567"
        self.assertEqual(remove_duplicate_related_ids([id_a, id_b], TARGET, {}), [id_b])
        self.assertEqual(remove_duplicate_related_ids([id_a], None, {}), [id_a])
        self.assertEqual(remove_duplicate_related_ids(
            [id_a, id_b], TARGET, {id_b: TARGET}), [])

    def test_fallback_uses_published_rare_entity_and_matching_topic(self):
        self.data["title"] = "ARTEX: новая проблема с ИИ-агентами"
        self.data["summary"] = "Сведения об инструменте ARTEX и возможных рисках"
        self.blocks[2]["text"] = "Эксперт упоминал ARTEX и другие средства кибератак."
        original = copy.deepcopy(self.blocks)
        site_blocks, after, row = select_site_card(
            self.data, self.blocks, self.records, self.site_links)
        self.assertEqual(row["id"], TARGET_ID)
        self.assertEqual(site_blocks, original)
        self.assertEqual(list(after), [2])

    def test_fallback_must_not_choose_merely_same_rubric_or_common_company(self):
        self.blocks[2]["text"] = "Microsoft и Google применяют технологии ИИ."
        site_blocks, after, row = select_site_card(
            self.data, self.blocks, self.records, self.site_links)
        self.assertEqual((after, row), ({}, None))
        self.assertIs(site_blocks, self.blocks)

    def test_fallback_rejects_one_off_benchmark_or_incidental_comparison(self):
        # Both topics match, but ARTEX appears once as an aside, not the subject.
        self.blocks[2]["text"] = (
            "В ходе сравнения также упоминался ARTEX, но новость посвящена другой системе."
        )
        source, cards, chosen = select_site_card(
            self.data, self.blocks, self.records, {})
        self.assertIs(source, self.blocks)
        self.assertEqual((cards, chosen), ({}, None))

    def test_fallback_accepts_repeated_specific_entity_in_body(self):
        self.blocks[2]["text"] = "Сотрудники впервые проверили ARTEX на сети."
        self.blocks[3]["text"] = "Второе испытание ARTEX подтвердило результаты."
        _, cards, chosen = select_site_card(
            self.data, self.blocks, self.records, {})
        self.assertEqual(chosen["id"], TARGET_ID)
        self.assertEqual(len(cards), 1)

    def test_unknown_editorial_dzen_link_prevents_auto_recommendation(self):
        self.data["title"] = "ARTEX: новые подробности"
        self.blocks[2]["text"] = (
            "Об ARTEX уже была [прошлая публикация](https://dzen.ru/a/unmapped-news)."
        )
        original = copy.deepcopy(self.blocks)
        site, cards, chosen = select_site_card(
            self.data, self.blocks, self.records, {})
        self.assertEqual((cards, chosen), ({}, None))
        self.assertEqual(site, original)
        self.assertIn('href="https://dzen.ru/a/unmapped-news"', render_blocks(site))

    def test_related_dzen_ids_prevent_fallback_without_inline_link(self):
        self.data["title"] = "ARTEX: новая публикация"
        self.data["related_dzen_ids"] = ["0123456789abcdef01234567"]
        self.blocks[2]["text"] = "Инструмент ARTEX получил дальнейшее развитие."
        _, cards, chosen = select_site_card(
            self.data, self.blocks, self.records, {})
        self.assertEqual((cards, chosen), ({}, None))

    def test_editorial_link_in_lead_quote_or_list_prevents_guess(self):
        self.data["title"] = "ARTEX: новая публикация"
        self.blocks[2]["text"] = "ARTEX получил дальнейшее развитие."
        target = "[контекст](https://dzen.ru/a/unmapped-reference)"
        for kind in ("lead", "quote", "ul"):
            blocks = copy.deepcopy(self.blocks)
            if kind == "lead":
                blocks[0]["text"] = "Новость с " + target + "."
            elif kind == "quote":
                blocks.insert(1, {"type": "quote", "text": "Цитировали " + target})
            else:
                blocks.insert(1, {"type": "ul", "items": ["Пункт с " + target]})
            _, cards, chosen = select_site_card(
                self.data, blocks, self.records, {})
            self.assertEqual((cards, chosen), ({}, None), kind)

    def test_future_or_unpublished_or_mismatched_topic_cannot_be_fallback(self):
        self.data["title"] = "ARTEX: новая публикация"
        self.blocks[2]["text"] = "Эксперт упоминал ARTEX и другие средства кибератак."
        for variant in (
            dict(TARGET, published="2026-11-12"),
            dict(TARGET, url="unpublished/article/"),
            dict(TARGET, topics=["video"]),
        ):
            _, after, row = select_site_card(self.data, self.blocks, [variant], {})
            self.assertEqual((after, row), ({}, None))

    def test_unknown_dzen_url_is_not_guessed(self):
        self.blocks[2]["text"] = "Написали о [взломе](https://dzen.ru/a/unknown)."
        self.data["topics"] = []
        _, after, row = select_site_card(self.data, self.blocks, self.records, {})
        self.assertEqual((after, row), ({}, None))

    def test_historical_dzen_imports_are_left_alone(self):
        self.data["dzen_id"] = "0123456789abcdef01234567"
        original = copy.deepcopy(self.blocks)
        blocks, after, row = select_site_card(
            self.data, self.blocks, self.records, self.site_links)
        self.assertEqual(blocks, original)
        self.assertEqual((after, row), ({}, None))

    def test_internal_site_url_can_trigger_exact_card(self):
        self.blocks[2]["text"] = ("Инструмент фигурировал в "
                                  "[расследовании](https://iipike.ru/" + TARGET["url"] + ").")
        site_blocks, after, row = select_site_card(self.data, self.blocks, self.records, {})
        self.assertEqual(row["id"], TARGET_ID)
        self.assertIn("в расследовании.", site_blocks[2]["text"])
        self.assertEqual(len(after), 1)


if __name__ == "__main__":
    unittest.main()
