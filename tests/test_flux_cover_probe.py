"""Offline Cloudflare FLUX smoke tests. Never make API calls."""
import base64
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import flux_cover_probe as flux


class CloudflareCoverTests(unittest.TestCase):
    def test_only_free_trial_model_and_three_requests(self):
        self.assertEqual(flux.MODEL, "@cf/black-forest-labs/flux-2-klein-4b")
        self.assertEqual((flux.WIDTH, flux.HEIGHT), (1024, 576))
        self.assertEqual(len(flux.CONCEPTS), 3)
        self.assertEqual(len({s["file"] for s in flux.CONCEPTS}), 3)

    def test_multipart_fields_include_boundary_and_dimensions(self):
        body, mime = flux.multipart_fields({
            "prompt": "test", "width": flux.WIDTH, "height": flux.HEIGHT
        })
        self.assertIn("multipart/form-data; boundary=", mime)
        boundary = mime.split("boundary=", 1)[1]
        self.assertIn(boundary.encode(), body)
        self.assertIn(b'name="height"', body)
        self.assertIn(b"576", body)

    def test_parse_base64_cloudflare_result(self):
        png = b"\x89PNG\r\n\x1a\nbinary-test"
        response = json.dumps({
            "success": True, "result": {"image": base64.b64encode(png).decode()}
        }).encode()
        self.assertEqual(flux.image_from_response(response, "application/json"), png)

    def test_refuse_broken_payloads(self):
        for response in [b"{}", b'{"success":false}', b'{"result":{"image":"invalid"}}']:
            with self.subTest(response=response):
                with self.assertRaises(RuntimeError):
                    flux.image_from_response(response, "application/json")

    def test_account_id_validation_prevents_request(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("called")):
            with self.assertRaisesRegex(RuntimeError, "Account ID"):
                flux.generate("invalid", "secret-token-0123456789", "prompt")

    def test_cyrillic_overlay_is_widescreen(self):
        from PIL import Image
        img = Image.new("RGB", (1024, 576), "cadetblue")
        out = io.BytesIO()
        img.save(out, format="PNG")
        cover = flux.make_cover(out.getvalue(), flux.CONCEPTS[0])
        self.assertEqual(cover.size, (1024, 576))
        self.assertEqual(cover.mode, "RGB")
        self.assertNotEqual(cover.getpixel((50, 500)), img.getpixel((50, 500)))

    def test_unique_concepts_have_no_generated_text_instruction(self):
        for item in flux.CONCEPTS:
            self.assertIn("NO TEXT", item["prompt"])
            self.assertIn("NO TYPOGRAPHY", item["prompt"])


if __name__ == "__main__":
    unittest.main()
