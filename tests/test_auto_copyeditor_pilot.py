"""Offline regressions: chief copyeditor may change style, not original facts or approvals."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.auto_editor_workbench import draft_template
from scripts.check_auto_copyeditor_pilot import FIELDS, blob_sha, validate


class ChiefCopyeditorPilotTests(unittest.TestCase):
    def setUp(self):
        receipt = {"status": "reserved", "request": "test-work-claim.json",
                   "claimed_at": "2026-11-23T09:00:00Z",
                   "pool_id": "n-123456789abcdef0", "pool_sequence": 25,
                   "article_id": "test-copyeditor-article"}
        doc = draft_template(receipt)
        doc["status"] = "ready_for_review"
        doc["revision"] = 2
        doc["updated_at"] = "2026-11-23T10:00:00Z"
        doc["content"].update({
            "title": "ИИ переписал статью о проверке сайтов",
            "dzen_title": "ИИ переписал статью о проверке сайтов",
            "summary": "Исследование о соблюдении правил.",
            "rubric": "news", "section": "НОВОСТИ ИИ",
            "source_url": "https://example.com/primary",
            "source_title": "Original study",
            "article_markdown": (
                "ИИ проверил 1 895 сайтов и получил 14,2% успешных ответов. "
                "Поэтому исследователи предложили новый механизм.\n\n"
                "Ссылка ведёт на [документ](https://example.com/study) с условиями.\n\n"
                "> «Мы изучили 14,2% записей», сообщили авторы.\n\n"
                "Завершающий абзац содержит точные факты об условиях испытания. "
                "Условия описаны самими исследователями в приложении к работе. "
                "Измерения проводились по одинаковому протоколу, чтобы результаты "
                "можно было сравнивать между разными системами. В публикации "
                "отдельно объясняются ограничения проверки и способ отбора."
            ),
            "threads_text": "ИИ изучил 1 895 сайтов. Детали у @OpenAI.",
            "x_text": "ИИ изучил 1 895 сайтов и обсудил условия.",
            "vk_title": "🔎 САЙТЫ и ИИ",
            "vk_summary": "Исследование проверило 1 895 сайтов."
        })
        doc["research"]["sources"] = ["https://example.com/primary"]
        doc["research"]["fact_checks"] = ["All numbers from source"]
        doc["cover_brief"].update(fact="Confirmed facts", hook="Important test",
                                   constraints="No invented result")
        self.doc = doc
        self.raw = (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode()
        original = {k: doc["content"][k] for k in FIELDS}
        edited = copy.deepcopy(original)
        edited["title"] = "Как ИИ проверил правила сайтов"
        edited["dzen_title"] = edited["title"]
        edited["article_markdown"] = (
            "ИИ проверил 1 895 сайтов и получил 14,2% успешных ответов.\n\n"
            "После этой проверки исследователи предложили новый механизм. "
            "Условия испытания описаны в [документе](https://example.com/study).\n\n"
            "> «Мы изучили 14,2% записей», сообщили авторы.\n\n"
            "В приложении к работе исследователи отдельно перечислили условия "
            "испытания и способ отбора. Измерения проводили по одинаковому "
            "протоколу, чтобы сравнивать результаты разных систем. "
            "Ограничения проверки тоже приведены в публикации."
        )
        self.candidate = {
            "schema_version": 2, "article_id": doc["article_id"],
            "source_revision": 2,
            "source_updated_at": doc["updated_at"],
            "source_draft_blob_sha": blob_sha(self.raw),
            "copyedit_version": 1, "status": "ready_for_comparison",
            "created_at": "2026-11-23T11:00:00Z",
            "worker": "hpii-chief-copyeditor",
            "original_text": original, "edited_text": edited,
            "change_log": ["Перестроен заголовок, лид отделён, порядок фактов изменён, "
                           "пустой переход удалён; сохранены все численные данные."],
            "editor_flags": [],
            "quality_review": {
                "source_event": "В исходнике говорится о проверке ИИ на 1 895 сайтах.",
                "main_problem": "Лид смешивал результат и редакторское объяснение, нарушая ритм.",
                "structural_action": "Результат вынесен отдельно, условия теста собраны рядом.",
                "reader_gain": "Читатель сразу узнаёт результат, затем детали проверки.",
                "fact_integrity": "Числа, цитата и первичная ссылка сохранены дословно."
            }
        }

    def check(self, c=None, raw=None):
        return validate(raw or self.raw, c or self.candidate,
                        filename="test-copyeditor-article-r2-v1.json")

    def test_safe_style_revision_keeps_original_unchanged(self):
        original = copy.deepcopy(self.doc)
        result = self.check()
        self.assertEqual(result["status"], "ready_for_comparison")
        self.assertEqual(original, self.doc)
        self.assertIn("Поэтому исследователи", self.doc["content"]["article_markdown"])

    def test_must_bind_original_git_blob_and_revision(self):
        altered = copy.deepcopy(self.candidate)
        altered["source_draft_blob_sha"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "blob mismatch"):
            self.check(altered)
        altered = copy.deepcopy(self.candidate)
        altered["source_revision"] = 3
        with self.assertRaisesRegex(ValueError, "revision"):
            self.check(altered)
        with self.assertRaisesRegex(ValueError, "filename"):
            validate(self.raw, self.candidate, filename="wrong-r2-v1.json")

    def test_numbers_links_handles_and_quotes_must_survive(self):
        for changed, expected in [
            ("1 895", "numerical"),
            ("14,2%", "numerical"),
            ("https://example.com/study", "URL"),
            ("@OpenAI", "handle"),
        ]:
            c = copy.deepcopy(self.candidate)
            fields = ["threads_text"] if changed == "@OpenAI" else [
                "article_markdown"]
            for field in fields:
                c["edited_text"][field] = c["edited_text"][field].replace(
                    changed, "изменено"
                )
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, expected):
                self.check(c)
        c = copy.deepcopy(self.candidate)
        c["edited_text"]["article_markdown"] = c["edited_text"]["article_markdown"].replace(
            "«Мы изучили", "«Мы проверили")
        with self.assertRaisesRegex(ValueError, "quotation"):
            self.check(c)

    def test_cannot_modify_metadata_or_invent_approval(self):
        for key, val in [("approved_by", "hpii-chief-copyeditor"),
                         ("research", {"sources": []}), ("source_url", "https://elsewhere")]:
            c = copy.deepcopy(self.candidate)
            c[key] = val
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "schema"):
                self.check(c)
        doc = copy.deepcopy(self.doc)
        doc["status"] = "drafting"
        raw = (json.dumps(doc, ensure_ascii=False) + "\n").encode()
        c = copy.deepcopy(self.candidate)
        c["source_draft_blob_sha"] = blob_sha(raw)
        with self.assertRaisesRegex(ValueError, "ready_for_review"):
            self.check(c, raw)

    def test_cosmetic_changes_cannot_be_called_successful(self):
        c = copy.deepcopy(self.candidate)
        c["edited_text"]["article_markdown"] = self.doc["content"]["article_markdown"]
        with self.assertRaisesRegex(ValueError, "Cosmetic article change"):
            self.check(c)
        # A rewritten headline plus a one-word change is still cosmetic.
        c["edited_text"]["article_markdown"] = self.doc["content"]["article_markdown"].replace(
            "новый механизм", "иной механизм")
        with self.assertRaisesRegex(ValueError, "Cosmetic article change"):
            self.check(c)

    def test_cliche_lead_and_audit_checks(self):
        c = copy.deepcopy(self.candidate)
        c["edited_text"]["article_markdown"] = (
            "Суть в том, что " + c["edited_text"]["article_markdown"])
        with self.assertRaisesRegex(ValueError, "Cliched editorial filler"):
            self.check(c)
        c = copy.deepcopy(self.candidate)
        c["quality_review"]["reader_gain"] = "Всё хорошо."
        with self.assertRaisesRegex(ValueError, "quality review diagnosis"):
            self.check(c)
        c = copy.deepcopy(self.candidate)
        c["edited_text"]["article_markdown"] = c["edited_text"]["article_markdown"].replace(
            "ИИ проверил 1 895 сайтов и получил 14,2% успешных ответов.\n\n",
            "ИИ проверил 1 895 сайтов и получил 14,2% успешных ответов. "
            "Это стало результатом эксперимента.\n\n")
        with self.assertRaisesRegex(ValueError, "standalone first sentence"):
            self.check(c)

    def test_editor_attention_can_preserve_unfixable_original(self):
        c = copy.deepcopy(self.candidate)
        c["edited_text"] = copy.deepcopy(c["original_text"])
        c["status"] = "needs_editor_attention"
        c["editor_flags"] = [
            "Исходник не объясняет критерий 14,2%: корректор не вправе его придумывать."
        ]
        self.assertEqual(self.check(c)["status"], "needs_editor_attention")

    def test_good_original_may_be_preserved_without_forced_rewrite(self):
        c = copy.deepcopy(self.candidate)
        c["edited_text"] = copy.deepcopy(c["original_text"])
        c["status"] = "no_change_recommended"
        self.assertEqual(self.check(c)["status"], "no_change_recommended")
        c["edited_text"]["title"] = "Заменённый заголовок"
        c["edited_text"]["dzen_title"] = "Заменённый заголовок"
        with self.assertRaisesRegex(ValueError, "No-change candidate"):
            self.check(c)

    def test_final_chief_editor_escalation_preserves_original(self):
        c = copy.deepcopy(self.candidate)
        c["status"] = "needs_chief_editor"
        c["edited_text"] = copy.deepcopy(c["original_text"])
        c["editor_flags"] = ["После ответа журналиста нельзя подтвердить центральный факт статьи."]
        self.assertEqual(self.check(c)["status"], "needs_chief_editor")
        c["editor_flags"] = []
        with self.assertRaisesRegex(ValueError, "Chief-editor escalation"):
            self.check(c)

    def test_escalation_requires_flags_clean_revisions_have_none(self):
        c = copy.deepcopy(self.candidate)
        c["status"] = "needs_editor_attention"
        with self.assertRaisesRegex(ValueError, "specific flag"):
            self.check(c)
        c["editor_flags"] = ["Текст содержит внутреннее противоречие: вернуть журналисту."]
        self.assertEqual(self.check(c)["status"], "needs_editor_attention")
        c["status"] = "ready_for_comparison"
        with self.assertRaisesRegex(ValueError, "cannot be presented"):
            self.check(c)


if __name__ == "__main__":
    unittest.main()
