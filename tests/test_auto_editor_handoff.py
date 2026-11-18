"""Offline guards for autonomous approved-text + approved-WebP handoff; no publication."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from scripts import auto_editor_handoff as h

ROOT=Path(__file__).resolve().parents[1]
ID="auto-handoff-offline-test-20261117"
REV=4
VERSION=1
TIME="2026-11-17T09:14:28.326Z"

def blob_sha(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()

def encoded(record):
    return (json.dumps(record,ensure_ascii=False,indent=2)+"\n").encode("utf-8")

class HandoffTests(unittest.TestCase):
    def fixture(self):
        image=Image.new("RGB",(1600,900),(16,74,121))
        buffer=BytesIO()
        image.save(buffer,format="WEBP",quality=76)
        webp=buffer.getvalue()
        content={
          "title":"Проверка автоматического редакционного комплекта 2026",
          "dzen_title":"Проверка автоматического редакционного комплекта 2026",
          "summary":"Пилотная проверка правильного сохранения изображения и отдельного согласия человека.",
          "rubric":"news","section":"НОВОСТИ ИИ","topics":["models","agents"],
          "companies":["google"],"products":["gemini"],
          "source_url":"https://example.org/verified-source",
          "source_title":"Test primary source",
          "event_date":"2026-11-10",
          "related_dzen_ids":["6ae2c0cf4d27f64e5d7851ae"],
          "site_crosslinks":{},
          "article_markdown":(
            "**Google** представила проверяемый пример в редакционном пилоте.\n\n"+
            "Это описание теста для проверки сохранения точного утверждённого текста и "+
            "его связи с оригиналом иллюстрации. Данные не отправляются на сайт и "+
            "не публикуются без человека. "*5+
            "\n\n## Проверка ссылок\n\n"+
            "Проверенная публикация [об известной модели](https://dzen.ru/a/auLAz00n9k5deFGu) "+
            "ранее выходила и в Дзене, и на сайте проекта. Проверяем, что адрес "+
            "корректно заменяется на сайт только при HTML-сборке. "*4),
          "vk_title":"ПИЛОТ СТАТЬИ: проверка","vk_summary":"Это только локальный тест.",
          "threads_text":"Текст для Threads: пилот","x_text":"Текст для X: пилот"
        }
        draft={"schema_version":1,"article_id":ID,"revision":REV,
          "updated_at":TIME,"status":"ready_for_review","pool_sequence":44,
          "content":content}
        paths=h.candidate_paths(ID,REV,VERSION)
        text={"article_id":ID,"revision":REV,"updated_at":TIME,
          "action":"approve_text","status":"text_approved_cover_pending",
          "decided_by":"AfterDark1000","decided_at":"2026-11-17T11:43:18.754Z"}
        cover={"schema_version":1,"article_id":ID,"text_revision":REV,
          "text_updated_at":TIME,"status":"ready_for_cover_review",
          "image_path":paths["cover_image"],"width":1600,"height":900}
        approved={"article_id":ID,"text_revision":REV,"cover_version":VERSION,
          "text_updated_at":TIME,"status":"cover_approved_handoff_pending",
          "action":"approve_cover","decided_by":"AfterDark1000",
          "decided_at":"2026-11-17T14:32:42.913Z"}
        objects={paths["draft"]:encoded(draft),paths["text"]:b"",
          paths["cover_meta"]:b"",paths["cover_image"]:webp,
          paths["decision"]:b""}
        text["draft_blob_sha"]=blob_sha(objects[paths["draft"]])
        objects[paths["text"]]=encoded(text)
        cover["source_draft_blob_sha"]=blob_sha(objects[paths["draft"]])
        cover["source_decision_blob_sha"]=blob_sha(objects[paths["text"]])
        cover["image_blob_sha"]=blob_sha(webp)
        objects[paths["cover_meta"]]=encoded(cover)
        approved.update({
          "cover_blob_sha":blob_sha(webp),
          "cover_metadata_blob_sha":blob_sha(objects[paths["cover_meta"]]),
          "source_draft_blob_sha":blob_sha(objects[paths["draft"]]),
          "source_text_decision_blob_sha":blob_sha(objects[paths["text"]])
        })
        objects[paths["decision"]]=encoded(approved)
        def fake_read(ref,path):
            self.assertEqual(ref,"origin/editorial-intake")
            data=objects[path]
            return data,blob_sha(data)
        return objects,fake_read,paths
    def test_handoff_stage_is_exact_preserves_markdown_and_translates_site_links(self):
        objects,reader,paths=self.fixture()
        with patch.object(h,"read_git",side_effect=reader):
            names,story_bytes,image,record_bytes=h.build_candidate(
                "origin/editorial-intake",ROOT,ID,REV,VERSION)
        story=json.loads(story_bytes)
        marker=json.loads(record_bytes)
        self.assertEqual(names,paths)
        self.assertEqual(image,objects[paths["cover_image"]])
        self.assertEqual(story["article_markdown"],
            json.loads(objects[paths["draft"]])["content"]["article_markdown"])
        self.assertEqual(story["site_crosslinks"],
            {"6ae2c0cf4d27f64e5d7851ae":"gemini4-carbon-ranking"})
        self.assertEqual(story["approved_by"],"human_editor")
        self.assertEqual(story["approved_at"],"2026-11-17")
        self.assertNotIn("threads_text",story)
        self.assertNotIn("x_text",story)
        self.assertEqual(marker["status"],"handed_off_to_site_queue")
        self.assertEqual(marker["social_posts"],"prepared_in_auto_draft_not_dispatched")
        self.assertLess(len(image),800000)
    def test_autonomous_vk_multiline_formatting_does_not_block_handoff(self):
        objects, reader, paths = self.fixture()
        raw = "\n\nМэтт добавил четыре коробки яиц.\n\nПользователь подтвердил заказ."
        draft = json.loads(objects[paths["draft"]])
        draft["content"]["vk_summary"] = raw
        # A changed draft must go through the full SHA approval chain; this
        # recreates those real content-addressed links without bypassing guards.
        objects[paths["draft"]] = encoded(draft)
        text = json.loads(objects[paths["text"]])
        text["draft_blob_sha"] = blob_sha(objects[paths["draft"]])
        objects[paths["text"]] = encoded(text)
        cover = json.loads(objects[paths["cover_meta"]])
        cover["source_draft_blob_sha"] = blob_sha(objects[paths["draft"]])
        cover["source_decision_blob_sha"] = blob_sha(objects[paths["text"]])
        objects[paths["cover_meta"]] = encoded(cover)
        approval = json.loads(objects[paths["decision"]])
        approval["source_draft_blob_sha"] = blob_sha(objects[paths["draft"]])
        approval["source_text_decision_blob_sha"] = blob_sha(objects[paths["text"]])
        approval["cover_metadata_blob_sha"] = blob_sha(objects[paths["cover_meta"]])
        objects[paths["decision"]] = encoded(approval)
        with patch.object(h, "read_git", side_effect=reader):
            names, story_bytes, image, record = h.build_candidate(
                "origin/editorial-intake", ROOT, ID, REV, VERSION)
        story = json.loads(story_bytes)
        self.assertEqual(story["vk_summary"], "Мэтт добавил четыре коробки яиц. Пользователь подтвердил заказ.")
        self.assertEqual(json.loads(objects[paths["draft"]])["content"]["vk_summary"], raw)
        self.assertEqual(story["article_markdown"], draft["content"]["article_markdown"])
        self.assertEqual(names, paths)
        self.assertEqual(image, objects[paths["cover_image"]])

    def test_change_to_cover_invalidates_approval(self):
        objects,reader,paths=self.fixture()
        cover=json.loads(objects[paths["cover_meta"]])
        cover["image_blob_sha"]="0"*40
        objects[paths["cover_meta"]]=encoded(cover)
        with patch.object(h,"read_git",side_effect=reader):
            with self.assertRaisesRegex(h.HandoffBlocked,"consistency mismatch"):
                h.build_candidate("origin/editorial-intake",ROOT,ID,REV,VERSION)
    def test_reworked_cover_without_approval_is_rejected(self):
        objects,reader,paths=self.fixture()
        approval=json.loads(objects[paths["decision"]])
        approval["action"]="revise_cover"
        objects[paths["decision"]]=encoded(approval)
        with patch.object(h,"read_git",side_effect=reader):
            with self.assertRaisesRegex(h.HandoffBlocked,"consistency mismatch"):
                h.build_candidate("origin/editorial-intake",ROOT,ID,REV,VERSION)
    def test_unsafe_extra_fields_are_dropped_and_wrong_ids_blocked(self):
        objects,reader,paths=self.fixture()
        draft=json.loads(objects[paths["draft"]]);draft["content"]["status"]="published"
        # Modifying an already-approved draft changes its SHA and breaks the whole chain.
        objects[paths["draft"]]=encoded(draft)
        with patch.object(h,"read_git",side_effect=reader):
            with self.assertRaisesRegex(h.HandoffBlocked,"consistency mismatch"):
                h.build_candidate("origin/editorial-intake",ROOT,ID,REV,VERSION)
        with self.assertRaisesRegex(h.HandoffBlocked,"Unsupported editorial"):
            h.build_candidate("origin/editorial-intake",ROOT,"bad/../id",REV,VERSION)
