"""Verify real WebP/base64 bridge locally, without network or GitHub mutations."""
import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw
from scripts.prepare_auto_cover_transfer import blob_sha, prepare


class CoverTransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.input = self.root / "scene.png"
        scene = Image.new("RGB", (1280, 720), (219, 201, 165))
        brush = ImageDraw.Draw(scene)
        brush.ellipse((150, 100, 530, 480), fill=(22, 63, 88))
        brush.rectangle((590, 200, 1100, 610), fill=(147, 54, 30))
        scene.save(self.input)

    def tearDown(self):
        self.tmp.cleanup()

    def test_real_webp_manifest_and_base64_reconstruct_same_git_blob(self):
        stem = "egg-story-test1234-r3-v1"
        info = prepare(self.input, self.root / "out", stem)
        folder = self.root / "out"
        data = (folder / (stem + ".webp")).read_bytes()
        encoded = "".join((folder / (stem + ".webp.b64")).read_text().split())
        saved = json.loads((folder / (stem + ".transfer.json")).read_text())
        self.assertEqual(info, saved)
        self.assertEqual(data, base64.b64decode(encoded, validate=True))
        self.assertEqual(info["git_blob_sha"], blob_sha(data))
        self.assertEqual(info["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(info["base64_chars"], len(encoded))
        self.assertEqual(info["base64_line_count"],
                         len((folder / (stem + ".webp.b64")).read_text().splitlines()))
        self.assertLessEqual(info["image_bytes"], 800_000)
        self.assertGreater(info["image_bytes"], 1024)
        self.assertEqual(data[:4], b"RIFF")
        self.assertEqual(data[8:12], b"WEBP")
        with Image.open(folder / (stem + ".webp")) as img:
            self.assertEqual(img.format, "WEBP")
            self.assertEqual(img.size, (1600, 900))

    def test_existing_output_is_not_silently_overwritten(self):
        stem = "egg-story-test1234-r3-v1"
        prepare(self.input, self.root / "out", stem)
        with self.assertRaises(FileExistsError):
            prepare(self.input, self.root / "out", stem)

    def test_bad_aspect_ratio_is_rejected(self):
        Image.new("RGB", (700, 700)).save(self.input)
        with self.assertRaises(ValueError):
            prepare(self.input, self.root / "out", "egg-story-r3-v1")

    def test_invalid_approval_filename_is_rejected(self):
        with self.assertRaises(ValueError):
            prepare(self.input, self.root / "out", "../overwrite.json")
        with self.assertRaises(ValueError):
            prepare(self.input, self.root / "out", "egg-story-r3-v9")


if __name__ == "__main__":
    unittest.main()
