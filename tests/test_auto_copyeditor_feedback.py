"""Read-only copyeditor feedback handoff tests; no publishing or GitHub writes."""
import copy
import json
import unittest
from unittest.mock import patch

from scripts.check_auto_copyeditor_pilot import blob_sha
from scripts.check_auto_copyeditor_feedback import (
    validate_response, pending, COPIES, DRAFTS, DECISIONS, RESPONSES,
)


class CopyeditFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.ident = "nvidia-science-test"
        self.name = self.ident + "-r1-v1.json"
        self.original = {
            "article_id": self.ident, "revision": 1, "status": "ready_for_review",
            "pool_id": "n-0123456789abcdef", "pool_sequence": 223,
            "request": "auto-test-claim.json", "editor_notes": [],
        }
        self.source_raw = json.dumps(self.original, ensure_ascii=False).encode()
        self.copyedit = {
            "schema_version": 2, "article_id": self.ident,
            "source_revision": 1, "copyedit_version": 1,
            "source_draft_blob_sha": blob_sha(self.source_raw),
            "status": "needs_editor_attention",
            "editor_flags": ["Уточнить, какую метрику измеряет сравнение."],
        }
        self.copy_raw = json.dumps(self.copyedit, ensure_ascii=False).encode()
        self.response = {
            "schema_version": 1, "article_id": self.ident,
            "source_revision": 1, "copyedit_version": 1,
            "source_draft_blob_sha": blob_sha(self.source_raw),
            "copyedit_blob_sha": blob_sha(self.copy_raw),
            "status": "needs_human_decision", "result_revision": None,
            "result_draft_blob_sha": None,
            "note": "Проверил доступный первоисточник. Точный смысл метрики не определён.",
            "checked_sources": ["https://example.org/primary"],
            "worker": "hpii-auto-editor", "created_at": "2026-11-24T03:00:00Z",
        }

    def check(self, response=None, result_raw=None):
        return validate_response(self.copy_raw, response or self.response,
                                 self.source_raw, result_raw, filename=self.name)

    def test_human_question_does_not_fake_draft_rewrite(self):
        self.assertEqual(self.check()["status"], "needs_human_decision")
        answer = copy.deepcopy(self.response)
        answer["result_revision"] = 2
        with self.assertRaisesRegex(ValueError, "must not pretend"):
            self.check(answer)

    def test_revised_response_is_sha_bound_and_requires_editor_note(self):
        result = copy.deepcopy(self.original)
        result["revision"] = 2
        result["editor_notes"].append(
            f"copyedit_feedback={self.name}; copyedit_sha={blob_sha(self.copy_raw)}"
        )
        raw = json.dumps(result, ensure_ascii=False).encode()
        reply = copy.deepcopy(self.response)
        reply.update(status="revised", result_revision=2,
                     result_draft_blob_sha=blob_sha(raw))
        self.assertEqual(self.check(reply, raw)["result_revision"], 2)
        wrong_raw = raw + b"\n"
        with self.assertRaisesRegex(ValueError, "exact next draft revision"):
            self.check(reply, wrong_raw)
        result["editor_notes"] = []
        raw = json.dumps(result, ensure_ascii=False).encode()
        reply["result_draft_blob_sha"] = blob_sha(raw)
        with self.assertRaisesRegex(ValueError, "feedback marker"):
            self.check(reply, raw)

    def test_copyedit_is_never_a_human_decision(self):
        response = copy.deepcopy(self.response)
        response["worker"] = "AfterDark1000"
        with self.assertRaisesRegex(ValueError, "autonomous editor"):
            self.check(response)
        response = copy.deepcopy(self.response)
        response["copyedit_blob_sha"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "SHA mismatch"):
            self.check(response)

    def test_pending_only_current_unanswered_undecided_revision(self):
        paths = {
            f"{COPIES}/{self.name}": self.copy_raw,
            f"{DRAFTS}/{self.ident}.json": self.source_raw,
        }
        def fake_list(_ref, folder):
            return [f"{COPIES}/{self.name}"] if folder == COPIES else []
        def fake_read(_ref, path):
            return paths.get(path)
        with patch("scripts.check_auto_copyeditor_feedback.files_at", side_effect=fake_list), \
             patch("scripts.check_auto_copyeditor_feedback.read_at", side_effect=fake_read):
            found = pending("example-branch")
            self.assertEqual([x["article_id"] for x in found], [self.ident])
            paths[f"{DECISIONS}/{self.ident}-r1.json"] = b'{"action":"approve_text"}'
            self.assertEqual(pending("example-branch"), [])
            paths.pop(f"{DECISIONS}/{self.ident}-r1.json")
            source = copy.deepcopy(self.original)
            source["revision"] = 2
            paths[f"{DRAFTS}/{self.ident}.json"] = json.dumps(source).encode()
            self.assertEqual(pending("example-branch"), [])

    def test_final_chief_editor_case_is_not_a_new_editor_request(self):
        terminal = dict(self.copyedit, status="needs_chief_editor")
        with patch("scripts.check_auto_copyeditor_feedback.files_at", side_effect=lambda ref, folder: [f"{COPIES}/{self.name}"] if folder == COPIES else []), \
             patch("scripts.check_auto_copyeditor_feedback.read_at", return_value=json.dumps(terminal).encode()):
            self.assertEqual(pending("example-branch"), [])

    def test_answered_feedback_not_pending(self):
        def fake_list(_ref, folder):
            if folder == COPIES:
                return [f"{COPIES}/{self.name}"]
            if folder == RESPONSES:
                return [f"{RESPONSES}/{self.name}"]
            return []
        with patch("scripts.check_auto_copyeditor_feedback.files_at", side_effect=fake_list):
            self.assertEqual(pending("example-branch"), [])


if __name__ == "__main__":
    unittest.main()
