"""Rich editor text is preserved but arbitrary HTML/unsafe links are never rendered."""
import unittest

from scripts.site_rich_text import inline_html, validate_blocks, render_blocks

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
