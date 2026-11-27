"""Validate and apply an owner correction without publishing a new article."""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.site_rich_text import markdown_to_blocks

ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHA = re.compile(r"[a-f0-9]{40}\Z")
RID = re.compile(r"[a-f0-9]{32}\Z")
DIR = Path("data/article_edits")


def json_text(data):
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def git_blob(path):
    raw = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def text_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def images(blocks):
    return [b for b in blocks if b["type"] == "image"]


def original_markdown(root, data):
    if "original_article_markdown" not in data:
        if "article_edit_id" in data:
            raise ValueError("Incomplete article revision provenance")
        return data.get("article_markdown")
    slug = data["slug"]
    original = data["original_article_markdown"]
    current = data["article_markdown"]
    marker = read(root / DIR / "applied" / (slug + ".json"))
    expected = {"schema_version": 1, "article_id": slug,
                "request_id": data.get("article_edit_id"),
                "original_sha256": text_hash(original),
                "edited_sha256": text_hash(current)}
    if marker != expected or not RID.fullmatch(str(expected["request_id"])):
        raise ValueError("Invalid article revision provenance")
    if images(markdown_to_blocks(original)) != images(markdown_to_blocks(current)):
        raise ValueError("Article edit must preserve existing illustrations")
    return original


def request_valid(req, slug):
    return (isinstance(req, dict)
            and set(req) == {"schema_version","article_id","request_id","base_sha","article_markdown"}
            and req["schema_version"] == 1 and req["article_id"] == slug
            and isinstance(req["request_id"], str) and RID.fullmatch(req["request_id"])
            and isinstance(req["base_sha"], str) and SHA.fullmatch(req["base_sha"])
            and isinstance(req["article_markdown"], str)
            and 1 <= len(req["article_markdown"].encode("utf-8")) <= 120000)


def apply_request(root, slug, req):
    from scripts.publish_approved_article import approved_article, render_article
    from scripts.site_related import catalog_entries
    from scripts.site_entities import load_registry
    from scripts.site_dossier import load_ids
    from scripts.build_dzen_rss import render as dzen_rss
    if not ID.fullmatch(slug) or len(slug) > 72 or not request_valid(req, slug):
        raise ValueError("Invalid article edit request")
    path = root / "content/approved" / (slug + ".json")
    page = root / "articles" / slug / "index.html"
    records = read(root / "news.json")
    row = next((r for r in records if r.get("id") == slug), None)
    if not row or not page.is_file() or not path.is_file():
        raise ValueError("Only an existing published article may be edited")
    if git_blob(path) != req["base_sha"]:
        raise ValueError("Article changed since opening; reload and reapply edits")
    data = approved_article(root, slug)
    if not isinstance(data.get("article_markdown"), str) or data.get("dzen_id"):
        raise ValueError("Only native site-first Markdown articles are supported")
    original = original_markdown(root, data)
    body = req["article_markdown"].strip()
    blocks = markdown_to_blocks(body)
    if images(blocks) != images(data["paragraphs"]):
        raise ValueError("Existing images and their order must remain unchanged")
    if body == data["article_markdown"]:
        return {}
    updated = dict(data, article_markdown=body, paragraphs=blocks,
                   original_article_markdown=original, article_edit_id=req["request_id"])
    marker = {"schema_version":1,"article_id":slug,"request_id":req["request_id"],
              "original_sha256":text_hash(original),"edited_sha256":text_hash(body)}
    catalog = catalog_entries(root) if data.get("related_dzen_ids") else {}
    html = render_article(updated, records, catalog, registry=load_registry(root),
                          dossier_ids=load_ids(root))
    rss = dzen_rss(root, records, staged=updated)
    return {path:json_text(updated), page:html, root/"dzen-rss.xml":rss,
            root/DIR/"applied"/(slug+".json"):json_text(marker)}


def process(root=ROOT):
    for path in sorted((root / DIR / "requests").glob("*.json")):
        slug = path.stem
        if not ID.fullmatch(slug) or len(slug) > 72:
            continue
        req = read(path)
        receipt = root / DIR / "receipts" / path.name
        if receipt.exists() and read(receipt).get("request_id") == req.get("request_id"):
            continue
        if not request_valid(req, slug):
            raise ValueError("Malformed request: "+slug)
        try:
            outputs = apply_request(root, slug, req)
            result = {"request_id":req["request_id"],"status":"applied" if outputs else "unchanged"}
        except ValueError as error:
            outputs = {}
            result = {"request_id":req["request_id"],"status":"rejected","error":str(error)[:700]}
        for dest, value in outputs.items():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(value, encoding="utf-8")
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json_text(result), encoding="utf-8")
        print("ARTICLE_EDIT", slug, result["status"], flush=True)
        return
    print("ARTICLE_EDIT idle", flush=True)


if __name__ == "__main__":
    process()
