"""Offline contract tests: no network and no API keys required."""
import importlib.util
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

FILE = Path(__file__).resolve().parents[1] / "scripts" / "shorts_format_hunter.py"
spec = importlib.util.spec_from_file_location("shorts_format_hunter", FILE)
hunter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hunter)

class HunterTests(unittest.TestCase):
    def test_duration(self):
        self.assertEqual(hunter.seconds_from_iso8601_duration("PT35S"), 35)
        self.assertEqual(hunter.seconds_from_iso8601_duration("PT2M10S"), 130)
        self.assertIsNone(hunter.seconds_from_iso8601_duration("bad"))

    def test_extract_model_output(self):
        obj = {"evidence_quality": "observed", "timeline": []}
        wrapped = {"status":"completed","steps":[
            {"type":"thought","content":[{"type":"text","text":"NOT OUTPUT"}]},
            {"type":"model_output","content":[{"type":"text","text":json.dumps(obj)}]}]}
        self.assertEqual(hunter.extract_output(wrapped), obj)
        with self.assertRaises(RuntimeError):
            hunter.extract_output({"steps":[]})

    def test_score_requires_published(self):
        video={"id":"a","published_at":hunter.iso(hunter.now_utc()-timedelta(hours=8)),
               "views":20000,"subscribers":2000}
        self.assertGreater(hunter.score_video(video), 0)

    def test_history_growth(self):
        t = hunter.iso(hunter.now_utc()-timedelta(hours=3))
        history={"items":{"abc":[{"checked_at":t,"views":1000,"likes":1}]}}
        value = hunter.history_growth({"id":"abc","views":1600},history)
        self.assertIsNotNone(value)
        self.assertAlmostEqual(value,200,delta=2)

    def test_no_gemini_secret_no_network_or_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(hunter,"RESULTS",Path(tmp)/"r.json"), \
                 patch.object(hunter,"HISTORY",Path(tmp)/"h.json"), \
                 patch.dict("os.environ",{"GEMINI_API_KEY":"","YOUTUBE_API_KEY":""}), \
                 patch.object(hunter,"request_json") as net:
                with self.assertRaisesRegex(RuntimeError,"Missing GEMINI_API_KEY"):
                    hunter.run("pilot")
                net.assert_not_called()
                self.assertFalse(hunter.RESULTS.exists())

    def test_pilot_without_youtube_key_is_not_verified_viral(self):
        observed = {k: "visible" for k in hunter.SCHEMA["required"]}
        observed["timeline"]=[]
        observed["evidence_quality"]="observed"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(hunter,"RESULTS",Path(tmp)/"r.json"), \
                 patch.object(hunter,"HISTORY",Path(tmp)/"h.json"), \
                 patch.dict("os.environ",{"GEMINI_API_KEY":"dummy","YOUTUBE_API_KEY":""}), \
                 patch.object(hunter,"analyze_gemini",return_value=observed) as call:
                hunter.run("pilot")
                result=json.loads(hunter.RESULTS.read_text())
                self.assertEqual(result["status"],"ok")
                self.assertEqual(len(result["videos"]),min(hunter.MAX_ANALYSES,4))
                self.assertTrue(all(v["viral_status"]=="unconfirmed" for v in result["videos"]))
                self.assertTrue(all(v["statistics_source"]=="unavailable" for v in result["videos"]))
                self.assertEqual(call.call_count,min(hunter.MAX_ANALYSES,4))

    def test_unsupported_view_is_not_analyzed(self):
        analysis={k:"not visible" for k in hunter.SCHEMA["required"]}
        analysis["timeline"]=[];analysis["evidence_quality"]="unsupported"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(hunter,"RESULTS",Path(tmp)/"r.json"), \
                 patch.object(hunter,"HISTORY",Path(tmp)/"h.json"), \
                 patch.dict("os.environ",{"GEMINI_API_KEY":"dummy","YOUTUBE_API_KEY":""}), \
                 patch.object(hunter,"analyze_gemini",return_value=analysis):
                with self.assertRaisesRegex(RuntimeError,"No videos"):
                    hunter.run("pilot")
                result=json.loads(hunter.RESULTS.read_text())
                self.assertEqual(result["status"],"partial")
                self.assertTrue(all(v["status"]=="unsupported" for v in result["videos"]))

if __name__=="__main__":
    unittest.main()
