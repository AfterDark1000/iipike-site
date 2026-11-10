"""Guard editor-approved Markdown against stray blank > quote separators."""
import copy
import json
import unittest
from unittest.mock import patch

from scripts.editorial_quote_guard import collect_repairs, normalize_empty_quote_markers
from scripts.site_rich_text import markdown_to_blocks


INTRO = "Проверенные факты и конкретные источники представлены редактором. " * 9
BODY = (INTRO +
        "\n\nИсточники уже проверили свидетельства по теме.\n\n"
        "> Это точный текст свидетельства с важными деталями.\n"
        ">\n"
        "> — Автор высказывания, должность\n\n"
        "Продолжение статьи с [документом](https://example.org/docs).")


class QuoteGuardTests(unittest.TestCase):
    def test_safe_empty_quote_marker_only(self):
        broken = BODY
        with self.assertRaisesRegex(ValueError, "Quote needs"):
            markdown_to_blocks(broken)
        repaired, removed = normalize_empty_quote_markers(broken)
        self.assertEqual(removed, (5,))
        self.assertEqual(repaired, broken.replace("\n>\n", "\n"))
        quote = next(b for b in markdown_to_blocks(repaired) if b["type"] == "quote")
        self.assertEqual(quote["text"], "Это точный текст свидетельства с важными деталями.")
        self.assertEqual(quote["attribution"], "Автор высказывания, должность")
        self.assertIn("[документом](https://example.org/docs)", repaired)

    def test_marker_with_space_tabs_and_nonempty_text_are_preserved(self):
        for marker in ("> ", ">  ", " \t>\t  "):
            broken = BODY.replace("\n>\n", "\n" + marker + "\n")
            fixed, removed = normalize_empty_quote_markers(broken)
            self.assertEqual(fixed, broken.replace("\n" + marker + "\n", "\n"))
            self.assertEqual(removed, (5,))
        for source in (
            INTRO + "\n\n>\n\n" + INTRO,
            INTRO + "\n\n> Quote is meaningful\n> — Author\n>\n" + INTRO,
            INTRO + "\n\n>\n> — Author\n\n" + INTRO,
            INTRO + "\n\n> Quote\n> Some details\n\n" + INTRO,
        ):
            self.assertEqual(normalize_empty_quote_markers(source), (source, ()))
        self.assertEqual(normalize_empty_quote_markers(INTRO), (INTRO, ()))

    def test_idempotent_and_keeps_quote_lines(self):
        fixed, changes = normalize_empty_quote_markers(BODY)
        twice, changes_again = normalize_empty_quote_markers(fixed)
        self.assertEqual(twice, fixed)
        self.assertFalse(changes_again)
        self.assertIn("> — Автор высказывания, должность", twice)

    def test_only_unpublished_approved_valid_repair_is_planned(self):
        current = {
            "id": "a-repaired-story", "status": "editor_approved",
            "approved_by": "human_editor",
            "title": "Согласованная статья",
            "article_markdown": BODY,
            "source_url": "https://example.org/source",
        }
        published = dict(current, id="b-published-story")
        unapproved = dict(current, id="c-unapproved-story",
                          status="draft")
        invalid = dict(current, id="d-invalid-story",
                       article_markdown=BODY + "\n\n>broken")
        items = [current, published, unapproved, invalid]
        def fake_git(*args):
            if args[:1] == ("show",) and args[1].endswith(":news.json"):
                return json.dumps([{"id": "b-published-story"}])
            if args[:1] == ("ls-tree",):
                return "".join("editorial_inbox/stories/" + d["id"] + ".json\n"
                               for d in items)
            if args[:1] == ("show",):
                item_id = args[1].split("/")[-1].removesuffix(".json")
                return json.dumps(next(x for x in items if x["id"] == item_id))
            raise AssertionError(args)
        with patch("scripts.editorial_quote_guard._git", side_effect=fake_git):
            repairs = collect_repairs()
        self.assertEqual(len(repairs), 1)
        fix = repairs[0]
        self.assertEqual(fix["id"], "a-repaired-story")
        self.assertEqual(fix["path"], "editorial_inbox/stories/a-repaired-story.json")
        self.assertEqual(fix["removed_lines"], [5])
        self.assertEqual(fix["repaired_markdown"], BODY.replace("\n>\n", "\n"))
        self.assertEqual(current["article_markdown"], BODY)

    def test_malformed_without_safe_separator_is_not_changed(self):
        broken = BODY.replace("\n>\n", "\n>bad\n")
        fixed, removed = normalize_empty_quote_markers(broken)
        self.assertEqual((fixed, removed), (broken, ()))
        with self.assertRaisesRegex(ValueError, "Quote needs"):
            markdown_to_blocks(broken)


if __name__ == "__main__":
    unittest.main()
