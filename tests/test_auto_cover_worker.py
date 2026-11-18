"""Offline tests: one approved text -> one isolated cover candidate, no publishing."""
import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.auto_cover_worker import eligible, prompt_for, render_webp
from scripts.check_auto_cover_pilot import git_blob_sha


class AutonomousCoverWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inbox = self.root / "editorial_inbox"
        for name in ("auto_drafts", "auto_decisions", "auto_covers", "auto_cover_decisions", "auto_handoffs"):
            (self.inbox / name).mkdir(parents=True)
        self.article_id = "sneaker-interview-satire"
        self.draft = {
            "article_id": self.article_id,
            "revision": 3,
            "updated_at": "2026-11-18T02:50:00.000Z",
            "status": "ready_for_review",
            "pool_sequence": 45,
            "content": {"title": "Блогер пришёл к ИИ-рекрутеру с кроссовком на голове"},
            "cover_brief": {
                "fact": "Постановочный скетч: человек с кроссовком разговаривает с вымышленным ИИ-интервьюером.",
                "hook": "Нелепое собеседование",
                "constraints": "Не выдавать за настоящую запись. Надпись «КРОССОВОК НА СОБЕСЕДОВАНИИ».",
            },
        }
        self.draft_file = self.inbox / "auto_drafts" / (self.article_id + ".json")
        self.decision_file = self.inbox / "auto_decisions" / (self.article_id + "-r3.json")
        self.save_draft()
        self.save_decision()

    def tearDown(self):
        self.temp.cleanup()

    def save_draft(self):
        self.draft_file.write_text(json.dumps(self.draft, ensure_ascii=False), encoding="utf-8")

    def save_decision(self, **overrides):
        decision = dict(
            article_id=self.article_id, revision=3,
            action="approve_text", status="text_approved_cover_pending",
            updated_at=self.draft["updated_at"],
            decided_at="2026-11-18T03:06:28.975Z",
            draft_blob_sha=git_blob_sha(self.draft_file.read_bytes()),
        )
        decision.update(overrides)
        self.decision_file.write_text(json.dumps(decision, ensure_ascii=False), encoding="utf-8")

    def test_approved_text_selected_without_carbon_specific_id(self):
        plan = eligible(self.root)
        self.assertEqual(plan["article_id"], self.article_id)
        self.assertEqual(plan["revision"], 3)
        self.assertEqual(plan["headline"], "КРОССОВОК НА СОБЕСЕДОВАНИИ")
        self.assertEqual(plan["style_index"], 0)
        prompt=prompt_for(plan)
        self.assertIn("SPORT SNEAKER ON TOP OF HIS HEAD",prompt)
        self.assertNotIn("КРОССОВОК НА СОБЕСЕДОВАНИИ",prompt)
        self.assertIn("no faux text",prompt)

    def test_never_run_on_unapproved_or_changed_text(self):
        self.decision_file.unlink()
        self.assertIsNone(eligible(self.root))
        self.save_decision(action="revise_text", status="feedback_pending_revision")
        self.assertIsNone(eligible(self.root))
        self.save_decision()
        self.draft["content"]["title"] = "Other text"
        self.save_draft()
        self.assertIsNone(eligible(self.root))

    def test_existing_cover_is_never_regenerated(self):
        plan = eligible(self.root)
        (self.root / plan["image_path"]).write_bytes(b"RIFFnot_a_valid_WebP")
        self.assertIsNone(eligible(self.root))
        (self.root / plan["image_path"]).unlink()
        (self.root / plan["meta_path"]).write_text("{}", encoding="utf-8")
        self.assertIsNone(eligible(self.root))

    def test_cover_is_real_webp_cyrillic_and_correct_ratio(self):
        plan = eligible(self.root)
        source = Image.new("RGB", (1024, 576), "#ac8e6a")
        raw = io.BytesIO()
        source.save(raw, format="PNG")
        generated = render_webp(raw.getvalue(), plan)
        self.assertEqual(generated[:4], b"RIFF")
        self.assertEqual(generated[8:12], b"WEBP")
        self.assertLess(len(generated), 750_001)
        with Image.open(io.BytesIO(generated)) as im:
            im.load()
            self.assertEqual(im.size, (1600, 900))


if __name__ == "__main__":
    unittest.main()
