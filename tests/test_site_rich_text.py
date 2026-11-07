"""Rich editor text is preserved but arbitrary HTML/unsafe links are never rendered."""
import unittest

from scripts.site_rich_text import inline_html, validate_blocks, render_blocks, markdown_to_blocks

SAMPLE = [
    {"type": "lead", "text": "ИИ проверил **факты**, но *выводы* редакции остаются."},
    {"type": "p", "text": "Подробнее в [первоисточнике](https://example.org/news?q=1&v=2)."},
    {"type": "h2", "text": "Как это устроено"},
    {"type": "ul", "items": ["**Точность**: исходные данные", "Проверка источника"]},
    {"type": "ol", "items": ["Сначала сайт", "Затем Дзен и кросспостинг"]},
    {"type": "quote", "text": "Это *проверяемое* заявление.", "attribution": "Представитель компании"},
]


class SiteRichTextTests(unittest.TestCase):
    def test_renders_real_semantic_html_with_inline_formatting(self):
        result = render_blocks(SAMPLE)
        self.assertIn('<p class="lead">ИИ проверил <strong>факты</strong>, но <em>выводы</em>', result)
        self.assertIn('<a class="editorial-inline-link" href="https://example.org/news?q=1&amp;v=2"', result)
        self.assertIn('target="_blank" rel="noopener noreferrer"', result)
        self.assertIn("<h2>Как это устроено</h2>", result)
        self.assertIn('<ul class="editorial-list"><li><strong>Точность</strong>: исходные данные</li>', result)
        self.assertIn('<ol class="editorial-list"><li>Сначала сайт</li>', result)
        self.assertIn('<blockquote class="editorial-quote"><p>Это <em>проверяемое</em> заявление.</p>', result)
        self.assertIn("<cite>Представитель компании</cite>", result)
        self.assertLess(result.index("<ul "), result.index("<ol "))
        self.assertLess(result.index("<ol "), result.index("<blockquote "))

    def test_inline_dzen_links_resolve_to_local_pages_without_changing_source(self):
        dzen = "https://dzen.ru/a/auC5RL9TIlQwHobn"
        other = "https://dzen.ru/a/atmwtd2iM0SVppvw"
        local = "https://iipike.ru/articles/deepseek-shutdown-override/"
        source = ("[DeepSeek](" + dzen + "?utm_source=share#top) "
                  "[NVIDIA](" + other + ") "
                  "[Источник](https://example.org/news)")
        output = inline_html(source, site_links={dzen: local})
        self.assertIn('href="' + local + '">DeepSeek</a>', output)
        self.assertNotIn("utm_source=share", output)
        self.assertIn('href="' + other + '" target="_blank"', output)
        self.assertIn('href="https://example.org/news" target="_blank"', output)
        self.assertIn(dzen, inline_html(source))
        self.assertIn(dzen, source)
        with self.assertRaises(ValueError):
            inline_html(source, site_links={dzen: "javascript:alert(1)"})

    def test_real_publisher_resolves_later_dzen_counterpart_without_legacy_id(self):
        from scripts.publish_approved_article import render_article
        dzen = "https://dzen.ru/a/auC5RL9TIlQwHobn"
        article = {
            "slug": "current-site-story", "title": "Тест",
            "summary": "Аннотация", "rubric": "news",
            "section": "НОВОСТИ ИИ", "published": "2026-11-05",
            "source_url": "https://example.org/original",
            "source_title": "Первоисточник",
            "cover": "assets/editorial/example.webp",
            "related_dzen_ids": [],
            "paragraphs": [{"type": "lead", "text": "Текст новости."},
                           {"type": "p", "text": "Наш [прошлый материал](" + dzen + ")."}],
        }
        records = [{
            "id": "earlier-site-story", "url": "articles/earlier-site-story/",
            "site_first_dzen_id": "6ae0b944bf532254301e86e7",
            "site_first_dzen_url": dzen,
        }]
        rendered = render_article(article, records=records)
        self.assertIn('href="https://iipike.ru/articles/earlier-site-story/"', rendered)
        self.assertNotIn('href="' + dzen + '"', rendered)
        self.assertNotIn("Версия в Дзене", rendered)

    def test_real_publisher_maps_inline_links_only_in_site_html(self):
        from scripts.publish_approved_article import render_article
        dzen = "https://dzen.ru/a/auC5RL9TIlQwHobn"
        original = "Мы [писали об этом](" + dzen + ") ранее."
        article = {
            "slug": "new-article", "title": "Проверка ссылок",
            "summary": "Краткое содержание", "rubric": "news",
            "section": "НОВОСТИ ИИ", "published": "2026-11-05",
            "source_url": "https://example.org/source",
            "source_title": "Первоисточник",
            "cover": "assets/editorial/image.webp",
            "related_dzen_ids": [],
            "paragraphs": [{"type": "lead", "text": "Вступление."},
                           {"type": "p", "text": original}],
            "article_markdown": original,
        }
        existing = [{"id": "deepseek-shutdown-override",
                     "dzen_id": "6ae0b944bf532254301e86e7",
                     "dzen_url": dzen,
                     "url": "articles/deepseek-shutdown-override/"}]
        html = render_article(article, records=existing)
        self.assertIn('href="https://iipike.ru/articles/deepseek-shutdown-override/"', html)
        self.assertNotIn('href="' + dzen + '"', html)
        self.assertEqual(article["article_markdown"], original)
        self.assertEqual(article["paragraphs"][1]["text"], original)

    def test_quotes_and_tags_are_escaped_even_in_malformed_markdown(self):
        text = 'Текст <script>alert(1)</script> и "**правда**" & ещё.'
        output = inline_html(text)
        self.assertNotIn("<script>", output)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", output)
        self.assertIn('&quot;<strong>правда</strong>&quot;', output)
        self.assertIn("&amp; ещё", output)

    def test_missing_or_unsafe_protocols_are_rejected_before_site_release(self):
        for target in ("javascript:alert(1)", "data:text/html,hello",
                       "http://example.org", "//example.org",
                       "https://user:pass@example.org/x", "https://example.org:8080/",
                       "https://example.org/evil\\@fake.net", "https://example.org/test%0a",
                       "ftp://example.org/"):
            with self.subTest(target=target):
                blocks = [dict(SAMPLE[0]),
                          {"type": "p", "text": "[Нажми](" + target + ")"}]
                # %0a is a percent-encoded URL component and safe as a plain
                # string; do not conflate with a literal control character.
                if target.endswith("%0a"):
                    validate_blocks(blocks)
                else:
                    with self.assertRaises(ValueError):
                        validate_blocks(blocks)

    def test_inline_html_and_links_are_safe_in_quote_and_list_items(self):
        blocks = [
            {"type": "lead", "text": "Проверка нормального заголовка."},
            {"type": "ul", "items": ['Один <img src=x onerror=alert(1)>',
                                      "[Читайте](https://example.org/a?x=1&z=2)"]},
            {"type": "quote", "text": 'Утверждение <svg/onload=alert(1)>',
             "attribution": "<Admin>"},
        ]
        result = render_blocks(blocks)
        self.assertNotIn("<img ", result)
        self.assertNotIn("<svg/", result)
        self.assertIn("&lt;svg/onload=alert(1)&gt;", result)
        self.assertIn("<cite>&lt;Admin&gt;</cite>", result)
        self.assertIn("https://example.org/a?x=1&amp;z=2", result)

    def test_verbatim_markdown_converts_complete_article_with_authored_formatting(self):
        original = (
            ("Редакторский **первый абзац** и *курсив*, сохранённые без ручного "
             "перенабора для сайта. " * 4)
            + "\n\n## Главный подзаголовок\n\n"
            + ("Официальный [документ](https://example.org/a?x=1&b=2) подробно "
               "рассказывает о новых событиях. " * 3)
            + "\n\n- **Первый факт** и подтверждение\n"
            + "- Второй факт\n\n"
            + "1. Сначала статья появляется на сайте\n"
            + "2. Затем в Дзене\n\n"
            + "> Об этом сообщил *руководитель* исследования.\n"
            + "> — Автор заявления\n\n"
            + "### Дополнительный раздел\n\n"
            + "Заключение подтверждает весь текст, а не только его краткую выжимку."
        )
        blocks = markdown_to_blocks(original)
        self.assertEqual([b["type"] for b in blocks],
                         ["lead", "h2", "p", "ul", "ol", "quote", "h3", "p"])
        self.assertEqual(blocks[5]["attribution"], "Автор заявления")
        output = render_blocks(blocks)
        self.assertIn("<strong>первый абзац</strong>", output)
        self.assertIn("<em>курсив</em>", output)
        self.assertIn("<h2>Главный подзаголовок</h2>", output)
        self.assertIn("<h3>Дополнительный раздел</h3>", output)
        self.assertIn('<ul class="editorial-list">', output)
        self.assertIn('<ol class="editorial-list">', output)
        self.assertIn("<blockquote", output)
        self.assertIn("https://example.org/a?x=1&amp;b=2", output)

    def test_markdown_rejects_unrepresentable_structure_instead_of_flattening(self):
        base = "Проверенная статья с большим числом фактов и достоверных источников. " * 9
        for extra in ("# Заголовок первого уровня", "#### Скрытый четвёртый уровень",
                      "~~~python", "---", "[x](javascript:alert(1))"):
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):
                    markdown_to_blocks(base + "\n\n" + extra)
        with self.assertRaisesRegex(ValueError, "complete"):
            markdown_to_blocks("Слишком мало")

    def test_stray_empty_quote_marker_is_rejected_before_publication(self):
        # Regression: Musk's 07.11.2026 release was blocked only at publish time
        # by a lone '>' between a direct quote and its attribution.
        intro = "Редакторская статья с подтверждёнными фактами и источниками. " * 10
        good = (intro + "\\n\\n> Точная цитата из выступления.\\n"
                "> — Автор высказывания")
        good = good.replace("\\n", "\n")
        parsed = markdown_to_blocks(good)
        self.assertEqual(parsed[-1]["type"], "quote")
        self.assertEqual(parsed[-1]["attribution"], "Автор высказывания")
        malformed = good.replace("\n> — Автор", "\n>\n> — Автор")
        with self.assertRaisesRegex(ValueError, "Quote needs"):
            markdown_to_blocks(malformed)

    def test_old_plain_text_article_blocks_still_work(self):
        old = [{"type": "lead", "text": "Первый обычный абзац."},
               {"type": "p", "text": "Второй без форматирования."},
               {"type": "h2", "text": "Обычный подзаголовок"}]
        self.assertEqual(render_blocks(old),
                         '<p class="lead">Первый обычный абзац.</p>\n'
                         '<p>Второй без форматирования.</p>\n'
                         '<h2>Обычный подзаголовок</h2>')

    def test_strict_block_structure_and_lengths(self):
        good = [{"type": "lead", "text": "Начало"}, {"type": "p", "text": "Текст"}]
        for bad in (
            [{"type": "p", "text": "Нет лида"}, {"type": "p", "text": "Продолжение"}],
            [good[0], {"type": "ul", "items": []}],
            [good[0], {"type": "ul", "items": "не список"}],
            [good[0], {"type": "ol", "items": [""]}],
            [good[0], {"type": "ul", "items": ["А"] * 25}],
            [good[0], {"type": "quote", "text": "  "}],
            [good[0], {"type": "iframe", "text": "XSS"}],
            [good[0], {"type": "p", "text": "Х"}, {"type": "lead", "text": "Повтор"}],
            [good[0], {"type": "ol", "items": ["Есть"], "text": "Нельзя одновременно"}],
            [good[0], {"type": "h2", "text": "Проверка", "items": ["Нельзя"]}],
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    validate_blocks(bad)


if __name__ == "__main__":
    unittest.main()
