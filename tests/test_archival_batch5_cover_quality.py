"""Prevent branded Dzen OpenGraph cards replacing original HPII cover art."""
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

def webp_dimensions(path):
    data=path.read_bytes()[:70]
    if data[:4]!=b"RIFF" or data[8:12]!=b"WEBP":
        raise ValueError("Not a valid WebP")
    if data[12:16]==b"VP8 ":
        i=data.find(b"\x9d\x01\x2a",20,60)
        if i<0: raise ValueError("No VP8 dimensions")
        return (int.from_bytes(data[i+3:i+5],"little")&0x3fff,
                int.from_bytes(data[i+5:i+7],"little")&0x3fff)
    if data[12:16]==b"VP8X":
        return (1+int.from_bytes(data[24:27],"little"),
                1+int.from_bytes(data[27:30],"little"))
    raise ValueError("Unsupported WebP dimensions")

class Batch5CoverQuality(unittest.TestCase):
    def test_repaired_covers_are_artwork_not_branded_dzen_cards(self):
        rows=json.loads((ROOT/"news.json").read_text(encoding="utf-8"))
        by_slug={x["id"]:x for x in rows}
        doc=json.loads((ROOT/"registry/batch5_cover_provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["original_og_cards_rejected"],16)
        self.assertEqual(doc["restored"],16)
        self.assertEqual(len(doc["entries"]),16)
        self.assertEqual(len({r["dzen_id"] for r in doc["entries"]}),16)
        for item in doc["entries"]:
            with self.subTest(item["slug"]):
                row=by_slug[item["slug"]]
                self.assertEqual(row["dzen_id"],item["dzen_id"])
                self.assertEqual(row["dzen_url"],item["dzen_url"])
                self.assertEqual(row["cover"],item["cover"])
                self.assertIn(item["source_type"],("dzen_feed_article_image","telegram_photo_of_same_dzen_article"))
                self.assertNotIn("get-zen-pub-og",item["source_url"])
                self.assertTrue(item["source_url"].startswith("https://t.me/iipike/") or
                                item["source_url"]==row["dzen_url"])
                p=ROOT/item["cover"]
                self.assertTrue(p.is_file())
                self.assertGreater(p.stat().st_size,15000)
                w,h=webp_dimensions(p)
                self.assertGreaterEqual(w,780)
                self.assertGreaterEqual(h,430)
                self.assertGreater(w/h,1.65)
                self.assertLess(w/h,1.86,"Dzen share card aspect is ~1.917, not original 16:9")

if __name__=="__main__":
    unittest.main()
