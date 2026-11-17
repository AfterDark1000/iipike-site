import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from scripts.migrate_legacy_draft_covers import migrate


class LegacyCoverMigrationTests(unittest.TestCase):
    def test_safe_migration_updates_only_draft_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            shelf=root/"drafts"
            shelf.mkdir()
            identifiers=["a"*20,"b"*20]
            (shelf/"index.json").write_text(json.dumps([{"id":x} for x in identifiers]))
            (shelf/"index.html").write_text("".join(f'<img src="{x}/cover.png">' for x in identifiers))
            before=[]
            for x in identifiers:
                folder=shelf/x
                folder.mkdir()
                Image.new("RGB",(1024,576),(40,60,80)).save(folder/"cover.png")
                (folder/"index.html").write_text('<figure><img src="cover.png"></figure>')
                before.append((folder/"cover.png").read_bytes())
            count,original_size,webp_size=migrate(root,False)
            self.assertEqual(count,2)
            self.assertGreater(original_size,webp_size)
            self.assertTrue((shelf/identifiers[0]/"cover.png").exists())
            count,_,_=migrate(root,True)
            self.assertEqual(count,2)
            for x in identifiers:
                self.assertFalse((shelf/x/"cover.png").exists())
                candidate=shelf/x/"cover.webp"
                self.assertTrue(candidate.exists())
                self.assertIn("cover.webp",(shelf/x/"index.html").read_text())
                with Image.open(candidate) as image:
                    self.assertEqual(image.format,"WEBP")
                    image.load()
                    self.assertEqual(image.size,(1024,576))
            self.assertNotIn("cover.png",(shelf/"index.html").read_text())
            self.assertEqual(migrate(root,False)[0],0)

    def test_fails_closed_if_reference_does_not_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            shelf=root/"drafts"
            folder=shelf/("c"*20)
            folder.mkdir(parents=True)
            (shelf/"index.json").write_text(json.dumps([{"id":"c"*20}]))
            (shelf/"index.html").write_text("missing reference")
            (folder/"index.html").write_text('<img src="cover.png">')
            Image.new("RGB",(1024,576),(50,50,50)).save(folder/"cover.png")
            with self.assertRaises(ValueError):
                migrate(root,True)
            self.assertTrue((folder/"cover.png").exists())
