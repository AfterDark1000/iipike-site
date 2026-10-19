import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gemini_probe as probe


class ProbeTests(unittest.TestCase):
    def test_uses_fixed_free_model(self):
        self.assertEqual(probe.MODEL, "gemini-3.5-flash-lite")
        self.assertTrue(probe.ENDPOINT.endswith("/gemini-3.5-flash-lite:generateContent"))

    def test_public_source_and_schema(self):
        with tempfile.TemporaryDirectory() as t:
            Path(t, "news.json").write_text(json.dumps([{
                "id": "google-search-ai-links", "title": "Тест",
                "summary": "Данные", "event_date": "2026-10-15",
                "source_url": "https://example.org/source"
            }]), encoding="utf-8")
            with patch.object(probe, "ROOT", Path(t)):
                payload = probe.build_payload()
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertIn("approved_for_publication", payload["generationConfig"]["responseSchema"]["required"])
        self.assertNotIn("google_search", json.dumps(payload).lower())

    def test_accepts_safe_candidate(self):
        obj = {"headline": "Заголовок", "lead": "Понятный лид",
               "fact_checks_needed": ["Проверить первоисточник"],
               "approved_for_publication": False}
        response = {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]}
        self.assertEqual(probe.extract_draft(response), obj)

    def test_blocks_auto_publication(self):
        obj = {"headline": "Заголовок", "lead": "Лид",
               "fact_checks_needed": [], "approved_for_publication": True}
        response = {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]}
        with self.assertRaisesRegex(RuntimeError, "publication flag"):
            probe.extract_draft(response)

    def test_blocks_no_candidates(self):
        with self.assertRaisesRegex(RuntimeError, "no candidates"):
            probe.extract_draft({"candidates": []})

    def test_blocks_invalid_json(self):
        response = {"candidates": [{"content": {"parts": [{"text": "<not-json>"}]}}]}
        with self.assertRaisesRegex(RuntimeError, "valid JSON"):
            probe.extract_draft(response)


if __name__ == "__main__":
    unittest.main()
