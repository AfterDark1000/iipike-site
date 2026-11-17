"""Stage-2 offline tests. No GitHub network, no publication, no real pool writes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.site_news_pool import add, next_item, validate as validate_pool
from scripts.auto_editor_workbench import (
    REQUESTS, RECEIPTS, POOL, claim_ordinary, article_slug, consume,
    draft_template, validate_draft, verify_drafts,
)

NOW = "2026-11-17T06:30:00+00:00"

def pool_with(*items):
    pool = {"schema_version": 1, "note": "Test candidates only.", "items": []}
    records = [{"title": name, "source_url": f"https://example.org/story/{j}",
                "priority": priority} for j, (name, priority) in enumerate(items, 1)]
    return add(pool, records, now=NOW)[0]

class AutoEditorClaimTests(unittest.TestCase):
    def test_hot_is_never_claimed_even_when_first(self):
        src = pool_with(("Hot headline for human", "high"),
                        ("Normal headline for automation", "normal"),
                        ("Another hot headline", "high"),
                        ("Low headline for automation", "low"))
        before = copy.deepcopy(src)
        updated, ticket = claim_ordinary(src, "request-0001.json", now=NOW)
        self.assertEqual(src, before)
        self.assertEqual(ticket["priority"], "normal")
        self.assertEqual(ticket["pool_sequence"], 2)
        self.assertEqual([x["status"] for x in updated["items"]],
                         ["queued", "in_review", "queued", "queued"])
        self.assertIn("AUTO_EDITOR claim=request-0001.json", updated["items"][1]["note"])
        validate_pool(updated)
        next_pool, manual = next_item(updated, now=NOW)
        self.assertEqual(manual["priority"], "high")
        self.assertEqual(manual["sequence"], 1)
        self.assertEqual(next_pool["items"][2]["status"], "queued")

    def test_only_hot_returns_no_candidate_and_no_mutation(self):
        src = pool_with(("Hot A", "high"), ("Hot B", "high"))
        updated, ticket = claim_ordinary(src, "request-0002.json", now=NOW)
        self.assertIsNone(ticket)
        self.assertEqual(updated, src)

    def test_low_is_allowed_only_in_standard_fifo(self):
        src = pool_with(("Old low", "low"), ("New normal", "normal"),
                        ("Hot for manual", "high"))
        updated, ticket = claim_ordinary(src, "request-0003.json", now=NOW)
        self.assertEqual(ticket["pool_sequence"], 1)
        self.assertEqual(ticket["priority"], "low")
        _, next_ticket = claim_ordinary(updated, "request-0004.json", now=NOW)
        self.assertEqual(next_ticket["pool_sequence"], 2)

    def test_does_not_steal_manual_in_review(self):
        src = pool_with(("Manual first", "normal"), ("Auto second", "normal"))
        manual, chosen = next_item(src, now=NOW)
        self.assertEqual(chosen["sequence"], 1)
        result, ticket = claim_ordinary(manual, "request-0005.json", now=NOW)
        self.assertEqual(ticket["pool_sequence"], 2)
        self.assertEqual(result["items"][0], manual["items"][0])

    def test_slug_stable_and_article_id_not_pool_id(self):
        src = pool_with(("ИИ проверил новости о космосе", "normal"))
        slug = article_slug(src["items"][0])
        self.assertTrue(slug.startswith("ii-proveril-novosti-o-kosmose-"))
        self.assertLessEqual(len(slug), 72)
        _, ticket = claim_ordinary(src, "request-0006.json", now=NOW)
        self.assertEqual(ticket["article_id"], slug)
        self.assertNotEqual(ticket["article_id"], ticket["pool_id"])

    def test_collision_never_reserves(self):
        src = pool_with(("Normal title", "normal"))
        used = {article_slug(src["items"][0])}
        with self.assertRaisesRegex(ValueError, "collision"):
            claim_ordinary(src, "request-0007.json", now=NOW, used_ids=used)
        self.assertEqual(src["items"][0]["status"], "queued")

    def test_bad_request_filename_refused(self):
        with self.assertRaises(ValueError):
            claim_ordinary(pool_with(("News title", "normal")), "../bad.json", now=NOW)

    def test_consumption_one_commit_plan_receipts_and_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / POOL).parent.mkdir(parents=True)
            (root / POOL).write_text(json.dumps(pool_with(
                ("The hot human headline", "high"),
                ("First ordinary story", "normal"),
                ("Second ordinary story", "normal")
            )), encoding="utf-8")
            (root / REQUESTS).mkdir(parents=True)
            paths = []
            for i in range(2):
                p = root / REQUESTS / f"request-000{i+1}.json"
                p.write_text(json.dumps({"schema_version": 1,
                                         "action": "claim_ordinary",
                                         "worker": "hpii-auto-editor"}), encoding="utf-8")
                paths.append(p)
            first = consume(root, now=NOW, paths=paths)
            state = json.loads((root / POOL).read_text())
            self.assertEqual([x["status"] for x in state["items"]],
                             ["queued", "in_review", "in_review"])
            self.assertEqual(first[paths[0].name]["pool_sequence"], 2)
            self.assertEqual(first[paths[1].name]["pool_sequence"], 3)
            self.assertEqual(first[paths[0].name]["status"], "reserved")
            self.assertNotEqual(first[paths[0].name]["article_id"],
                                first[paths[1].name]["article_id"])
            self.assertTrue((root / RECEIPTS / paths[0].name).is_file())
            again = consume(root, now=NOW, paths=paths)
            self.assertEqual(again, {})
            self.assertEqual(state, json.loads((root / POOL).read_text()))
            paths[0].write_text('{"schema_version":1,"action":"claim_ordinary","worker":"evil"}')
            with self.assertRaisesRegex(ValueError, "edited after processing"):
                consume(root, now=NOW, paths=paths)

    def test_malicious_request_rejected_no_hot_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / POOL).parent.mkdir(parents=True)
            original = pool_with(("Only hot story", "high"))
            (root / POOL).write_text(json.dumps(original), encoding="utf-8")
            (root / REQUESTS).mkdir(parents=True)
            path = root / REQUESTS / "bad-file.json"
            path.write_text(json.dumps({
                "schema_version": 1, "action": "claim_ordinary",
                "worker": "hpii-auto-editor", "priority": "high",
                "status": "editor_approved"
            }), encoding="utf-8")
            res = consume(root, now=NOW, paths=[path])
            self.assertEqual(res[path.name]["status"], "rejected")
            self.assertEqual(json.loads((root / POOL).read_text()), original)

    def test_only_hot_request_is_acknowledged_no_ordinary_news(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / POOL).parent.mkdir(parents=True)
            state = pool_with(("Only hot news", "high"))
            (root / POOL).write_text(json.dumps(state), encoding="utf-8")
            (root / REQUESTS).mkdir(parents=True)
            p = root / REQUESTS / "request-empty.json"
            p.write_text('{"schema_version":1,"action":"claim_ordinary","worker":"hpii-auto-editor"}')
            res = consume(root, now=NOW, paths=[p])
            self.assertEqual(res[p.name]["status"], "no_ordinary_news")
            self.assertEqual(state, json.loads((root / POOL).read_text()))

class AutoEditorDraftTests(unittest.TestCase):
    def setUp(self):
        src = pool_with(("Normal test story", "normal"))
        _, ticket = claim_ordinary(src, "request-draft.json", now=NOW)
        self.receipt = {"schema_version": 1, "request": "request-draft.json",
                        "status": "reserved", **ticket}
        self.draft = draft_template(self.receipt)

    def make_ready(self):
        d = copy.deepcopy(self.draft)
        d["status"] = "ready_for_review"
        body = d["content"]
        body.update({
            "title": "Проверенная статья о работе ИИ",
            "dzen_title": "Проверенная статья о работе ИИ",
            "summary": "Содержательное описание.",
            "rubric": "news", "section": "НОВОСТИ ИИ",
            "source_url": "https://example.org/primary",
            "source_title": "Official test source",
            "article_markdown": ("Это проверенный содержательный лид, который раскрывает новость. "
                                 "Здесь присутствуют все необходимые подробности и контекст для читателя.\n\n"
                                 "Во втором абзаце появляется информация об условиях тестирования "
                                 "и реальных ограничениях результата, без выдуманных цифр.\n\n"
                                 "## Что действительно сделали\n\n"
                                 "Следующий абзац рассказывает о проверенной технологии и о том, "
                                 "что изменилось для пользователей. Факты объяснены понятно "
                                 "и без рекламных обещаний. Пример достаточно длинный для "
                                 "использования валидатора готового Markdown.\n\n"
                                 "Финал заканчивается подтверждённым фактом."),
            "threads_text": "ИИ получил конкретную новую возможность.",
            "x_text": "ИИ показал новую возможность в официальной демонстрации.",
            "vk_title": "🤖 ИИ ПОКАЗАЛ новую возможность",
            "vk_summary": "Разработчики объяснили условия теста."
        })
        d["research"]["sources"] = ["https://example.org/primary"]
        d["research"]["fact_checks"] = ["Only scenario in this unit test"]
        d["cover_brief"] = {"fact": "Confirmed demonstration",
                            "hook": "What is new", "constraints": "No fictitious metrics"}
        return d

    def test_drafting_stub_is_allowed_for_resume(self):
        self.assertEqual(validate_draft(self.draft, self.receipt), self.draft)

    def test_ready_requires_complete_bundle(self):
        d = copy.deepcopy(self.draft)
        d["status"] = "ready_for_review"
        with self.assertRaisesRegex(ValueError, "missing"):
            validate_draft(d, self.receipt)
        self.assertEqual(validate_draft(self.make_ready(), self.receipt)["status"],
                         "ready_for_review")

    def test_no_approval_metadata_or_wrong_claim(self):
        d = self.make_ready()
        d["approved_by"] = "human_editor"
        with self.assertRaisesRegex(ValueError, "forbidden"):
            validate_draft(d, self.receipt)
        d = self.make_ready()
        d["pool_id"] = "n-deadbeefdeadbeef"
        with self.assertRaisesRegex(ValueError, "claim binding"):
            validate_draft(d, self.receipt)

    def test_ready_social_limits_strict(self):
        d = self.make_ready()
        d["content"]["threads_text"] = "a" * 481
        with self.assertRaisesRegex(ValueError, "too long"):
            validate_draft(d, self.receipt)
        d = self.make_ready()
        d["content"]["x_text"] = "a" * 281
        with self.assertRaisesRegex(ValueError, "too long"):
            validate_draft(d, self.receipt)
        d = self.make_ready()
        d["content"]["vk_title"] = "a" * 201
        with self.assertRaisesRegex(ValueError, "too long"):
            validate_draft(d, self.receipt)

    def test_drafts_only_in_separate_directory_and_with_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts = root / "drafts"
            receipts = root / "receipts"
            drafts.mkdir()
            receipts.mkdir()
            path = drafts / (self.draft["article_id"] + ".json")
            path.write_text(json.dumps(self.draft), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Missing confirmed"):
                verify_drafts(drafts, receipts)
            (receipts / self.receipt["request"]).write_text(
                json.dumps(self.receipt), encoding="utf-8")
            self.assertEqual(verify_drafts(drafts, receipts),
                             [self.draft["article_id"]])

    def test_approved_status_forbidden_even_with_complete_text(self):
        d = self.make_ready()
        d["status"] = "editor_approved"
        with self.assertRaisesRegex(ValueError, "status"):
            validate_draft(d, self.receipt)

if __name__ == "__main__":
    unittest.main()
