"""Stage-2 offline tests. No GitHub network, no publication, no real pool writes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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

    def test_linked_primary_and_related_groups_are_skipped_in_fifo(self):
        src = pool_with(("Linked lead", "normal"),
                        ("Linked companion", "normal"),
                        ("Group-tagged normal news", "normal"),
                        ("Stand-alone news", "normal"))
        before = copy.deepcopy(src)
        a, b, c, d = [i["id"] for i in src["items"]]
        routes = {
            a: {"sequence": 1, "pool_id": a, "lane": "long",
                "decision": "linked_primary", "group": "g1", "group_primary": 1},
            b: {"sequence": 2, "pool_id": b, "lane": "long",
                "decision": "linked_secondary", "group": "g1", "group_primary": 1},
            c: {"sequence": 3, "pool_id": c, "lane": "long",
                "decision": "full", "group": "g2", "group_primary": 3},
            d: {"sequence": 4, "pool_id": d, "lane": "long", "decision": "full"},
        }
        updated, ticket = claim_ordinary(src, "request-solo.json",
                                         now=NOW, routing=routes)
        self.assertEqual(ticket["pool_sequence"], 4)
        self.assertEqual(src, before)
        self.assertEqual([i["status"] for i in updated["items"]],
                         ["queued", "queued", "queued", "in_review"])

    def test_production_requires_explicit_full_long_route(self):
        src = pool_with(("Unclassified news", "normal"), ("Standalone news", "normal"))
        item = src["items"][1]
        routes = {item["id"]: {"sequence": 2, "pool_id": item["id"],
                                "lane": "long", "decision": "full"}}
        _, ticket = claim_ordinary(src, "request-strict.json", now=NOW,
                                   routing=routes, strict_routes=True)
        self.assertEqual(ticket["pool_sequence"], 2)
        _, ticket = claim_ordinary(src, "request-strict.json", now=NOW,
                                   routing={}, strict_routes=True)
        self.assertIsNone(ticket)

    def test_linked_only_returns_no_candidate_without_rewriting_pool(self):
        src = pool_with(("Linked lead", "normal"),
                        ("Linked secondary", "normal"))
        a, b = [i["id"] for i in src["items"]]
        routes = {
            a: {"sequence": 1, "pool_id": a, "lane": "long",
                "decision": "linked_primary"},
            b: {"sequence": 2, "pool_id": b, "lane": "hold",
                "decision": "linked_secondary", "group": "g", "group_primary": 1},
        }
        updated, ticket = claim_ordinary(src, "request-linked.json",
                                         now=NOW, routing=routes)
        self.assertIsNone(ticket)
        self.assertEqual(updated, src)

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

    def test_five_claims_per_rolling_24_hours_is_a_hard_server_guard(self):
        # Even if Work sends six valid requests in one push, the sixth
        # cannot reserve a news item or consume the editor's next-day quota.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / POOL).parent.mkdir(parents=True)
            stories = [(f"Ordinary news headline {i}", "normal") for i in range(1, 8)]
            original = pool_with(*stories)
            (root / POOL).write_text(json.dumps(original), encoding="utf-8")
            (root / REQUESTS).mkdir(parents=True)
            paths = []
            for n in range(1, 7):
                path = root / REQUESTS / f"work-production-{n:03}.json"
                path.write_text(json.dumps({"schema_version": 1,
                    "action": "claim_ordinary", "worker": "hpii-auto-editor"}), encoding="utf-8")
                paths.append(path)
            done = consume(root, now=NOW, paths=paths)
            self.assertEqual([done[x.name]["status"] for x in paths],
                             ["reserved"] * 5 + ["rejected"])
            self.assertIn("AUTO_EDITOR_DAILY_CAP_5", done[paths[-1].name]["error"])
            state = json.loads((root / POOL).read_text(encoding="utf-8"))
            self.assertEqual([x["status"] for x in state["items"]],
                             ["in_review"] * 5 + ["queued"] * 2)
            self.assertEqual(consume(root, now=NOW, paths=paths), {})
            next_path = root / REQUESTS / "work-production-next-day.json"
            next_path.write_text(json.dumps({"schema_version": 1,
                "action": "claim_ordinary", "worker": "hpii-auto-editor"}), encoding="utf-8")
            future = consume(root, now="2026-11-18T06:30:01+00:00", paths=[next_path])
            self.assertEqual(future[next_path.name]["status"], "reserved")
            self.assertEqual(future[next_path.name]["pool_sequence"], 6)

    def test_existing_recent_receipts_count_toward_five_article_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / POOL).parent.mkdir(parents=True)
            original = pool_with(("One still unclaimed headline", "normal"))
            (root / POOL).write_text(json.dumps(original), encoding="utf-8")
            (root / REQUESTS).mkdir(parents=True)
            (root / RECEIPTS).mkdir(parents=True)
            for n in range(5):
                r = {"schema_version": 1, "request": f"past-work-{n}.json",
                     "request_sha256": "placeholder", "status": "reserved",
                     "article_id": f"already-claimed-{n}",
                     "claimed_at": NOW, "worker": "hpii-auto-editor"}
                (root / RECEIPTS / r["request"]).write_text(
                    json.dumps(r), encoding="utf-8")
            path = root / REQUESTS / "new-production-request.json"
            path.write_text(json.dumps({"schema_version": 1,
                "action": "claim_ordinary", "worker": "hpii-auto-editor"}), encoding="utf-8")
            report = consume(root, now=NOW, paths=[path])
            self.assertEqual(report[path.name]["status"], "rejected")
            self.assertIn("AUTO_EDITOR_DAILY_CAP_5", report[path.name]["error"])
            self.assertEqual(json.loads((root / POOL).read_text()), original)

    def test_dispatch_request_never_reserves_substitute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pool = pool_with(("First ordinary news", "normal"), ("Second ordinary news", "normal"))
            (root / POOL).parent.mkdir(parents=True)
            (root / POOL).write_text(json.dumps(pool), encoding="utf-8")
            (root / REQUESTS).mkdir(parents=True)
            from scripts.editorial_routing import ROUTES
            (root / ROUTES).write_text("{}", encoding="utf-8")
            routes = {i["id"]: {"lane":"long","decision":"full"} for i in pool["items"]}
            path = root / REQUESTS / "dispatch-exact.json"
            path.write_text(json.dumps({"schema_version":2,"action":"claim_ordinary",
                "worker":"hpii-auto-editor","dispatch_sha":"a"*40}), encoding="utf-8")
            with patch("scripts.editorial_routing.load_routes", return_value=routes), \
                 patch("scripts.auto_editor_workbench.check_dispatch", return_value=pool["items"][1]["id"]):
                result = consume(root, now=NOW, paths=[path])
            self.assertEqual(result[path.name]["status"], "rejected")
            self.assertIn("DISPATCH_FIFO_CHANGED", result[path.name]["error"])
            self.assertEqual(json.loads((root / POOL).read_text()), pool)

    def test_dispatch_request_can_reserve_exact_fifo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pool = pool_with(("First ordinary news", "normal"))
            (root / POOL).parent.mkdir(parents=True)
            (root / POOL).write_text(json.dumps(pool), encoding="utf-8")
            (root / REQUESTS).mkdir(parents=True)
            from scripts.editorial_routing import ROUTES
            (root / ROUTES).write_text("{}", encoding="utf-8")
            routes = {i["id"]: {"lane":"long","decision":"full"} for i in pool["items"]}
            path = root / REQUESTS / "dispatch-exact.json"
            path.write_text(json.dumps({"schema_version":2,"action":"claim_ordinary",
                "worker":"hpii-auto-editor","dispatch_sha":"a"*40}), encoding="utf-8")
            with patch("scripts.editorial_routing.load_routes", return_value=routes), \
                 patch("scripts.auto_editor_workbench.check_dispatch", return_value=pool["items"][0]["id"]):
                result = consume(root, now=NOW, paths=[path])
            self.assertEqual(result[path.name]["status"],"reserved")
            self.assertEqual(result[path.name]["pool_id"],pool["items"][0]["id"])

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

    def test_new_human_made_ai_rubric_allowed_without_approval(self):
        from scripts.site_rubrics import RUBRICS as site_rubrics
        from scripts.auto_editor_workbench import RUBRICS as draft_rubrics
        self.assertEqual(set(draft_rubrics), set(site_rubrics))
        ready = self.make_ready()
        ready["content"]["rubric"] = "made-with-ai"
        ready["content"]["section"] = "СДЕЛАНО С ИИ"
        self.assertEqual(validate_draft(ready, self.receipt)["status"], "ready_for_review")

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
