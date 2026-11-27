import json
import shutil
import tempfile
import unittest
from pathlib import Path
from scripts.site_article_edits import apply_request, git_blob, original_markdown, process, DIR
from scripts.publish_approved_article import approved_article
from scripts.site_rich_text import markdown_to_blocks

ROOT=Path(__file__).resolve().parents[1]
SID="russian-ai-subscriptions-investigation-20261127"

class ArticleEditTests(unittest.TestCase):
    def test_real_source_correction_preserves_identity_and_original(self):
        # Use a real published snapshot, not a synthetic renderer stub.
        source=ROOT/"content/approved"/(SID+".json")
        original=json.loads(source.read_text())
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for rel in ["news.json","data/entity_registry.json","data/dossier.json",
                        "data/dzen_rss_export.json","data/editorial_full_catalog_snapshot.json",
                        "content/approved/"+SID+".json","articles/"+SID+"/index.html",original["cover"]]:
                src=ROOT/rel
                if src.is_file():
                    dest=root/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)
            marker=ROOT/DIR/"applied"/(SID+".json")
            if marker.is_file():
                target=root/DIR/"applied"/marker.name
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(marker,target)
            assets=ROOT/"assets/editorial/inline"/SID
            if assets.exists():
                shutil.copytree(assets,root/"assets/editorial/inline"/SID)
            path=root/"content/approved"/(SID+".json")
            body=original["article_markdown"]
            source_original=original.get("original_article_markdown",body)
            req={"schema_version":1,"article_id":SID,"request_id":"a"*32,
                 "base_sha":git_blob(path),"article_markdown":body+"\n\n**Контрольная тестовая правка.**"}
            outputs=apply_request(root,SID,req)
            self.assertIn(path,outputs)
            new=json.loads(outputs[path])
            self.assertEqual(new["original_article_markdown"],source_original)
            for key in ("slug","title","cover","published_at_utc","source_url"):
                self.assertEqual(original[key],new[key])
            for dest,value in outputs.items():
                dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(value)
            self.assertEqual(approved_article(root,SID)["article_markdown"],req["article_markdown"])
            self.assertEqual(original_markdown(root,new),source_original)
            self.assertIn("Контрольная тестовая правка.",(root/"dzen-rss.xml").read_text())
            self.assertIn("<strong>",(root/"articles"/SID/"index.html").read_text())
            with self.assertRaisesRegex(ValueError,"changed since opening"):
                apply_request(root,SID,req)
            req["base_sha"]=git_blob(path)
            # Remove exactly one existing image rather than relying on its caption.
            import re
            req["article_markdown"]=re.sub(r"^!\[[^\n]+\]\([^\n]+\)\s*$","",req["article_markdown"],count=1,flags=re.M)
            with self.assertRaisesRegex(ValueError,"images and their order"):
                apply_request(root,SID,req)
