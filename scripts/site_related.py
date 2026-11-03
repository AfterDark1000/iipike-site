"""Read-only, provenance-gated link resolution for the HPII historical Dzen catalog.

Do not confuse a URL reconstructed from an old seen ID with a verified public link.
Suggestions are not automatically published: editors select related_dzen_ids.
"""
import base64
from html import escape
import json
from pathlib import Path
import re

ID = re.compile(r"[0-9a-f]{24}\Z")
FILE = Path("data/editorial_full_catalog_snapshot.json")
DIARY = "6ae2f63c8b88aa0944624805"


def catalog_entries(root):
    path = root / FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("entries"), list):
        raise ValueError("Invalid historical catalog snapshot")
    return {entry["dzen_id"]: entry for entry in data["entries"]
            if isinstance(entry, dict) and isinstance(entry.get("dzen_id"), str)}


def verified(entry):
    if not isinstance(entry, dict) or not ID.fullmatch(entry.get("dzen_id") or ""):
        return False
    if entry["dzen_id"] == DIARY or not isinstance(entry.get("title"), str) or not entry["title"].strip():
        return False
    if (entry.get("url_evidence") != "recorded_in_editorial_archive"
            or entry.get("title_evidence") != "recorded"):
        return False
    ident = entry["dzen_id"]
    slug = base64.urlsafe_b64encode(bytes.fromhex(ident)).decode("ascii").rstrip("=")
    return entry.get("dzen_url") == "https://dzen.ru/a/" + slug


def validate_reference(ref, catalog):
    if not isinstance(ref, str) or not ID.fullmatch(ref) or ref == DIARY:
        raise ValueError("Invalid Dzen article reference")
    item = catalog.get(ref)
    if not verified(item):
        raise ValueError("Unverified Dzen article reference: " + ref)
    return item


def validate_links(ids, catalog, current=None):
    if (not isinstance(ids, list) or len(ids) > 4
            or not all(isinstance(ident, str) for ident in ids)
            or len(ids) != len(set(ids))):
        raise ValueError("Related articles must be a list of up to 4 unique Dzen IDs")
    for ident in ids:
        if ident == current:
            raise ValueError("Cannot link article to itself")
        validate_reference(ident, catalog)


def render_links(ids, records, catalog):
    """Prefer an existing iipike.ru article, else link to verified Dzen original."""
    if not ids:
        return ""
    local = {r["dzen_id"]: r for r in records if r.get("dzen_id")}
    links = []
    for ident in ids:
        row = validate_reference(ident, catalog)
        if ident in local:
            dest = "../../" + local[ident]["url"]
            title = local[ident]["title"]
            target = ""
            badge = "На сайте"
        else:
            dest = row["dzen_url"]
            title = row["title"]
            target = ' target="_blank" rel="noopener noreferrer"'
            badge = "В Дзене"
        links.append('<li><a href="' + escape(dest, quote=True) + '"' + target + '>'
                     + escape(title) + '</a> <small>(' + badge + ')</small></li>')
    return ('<nav class="related-stories" aria-label="Читайте также"><h2>Читайте также</h2><ul>'
            + "\n".join(links) + "</ul></nav>")


def suggest(data, catalog, limit=6):
    """Advisory title/excerpt overlap; never claims semantic verification."""
    stop = {"этот", "такой", "когда", "своей", "свой", "после", "перед", "были",
            "снова", "чтобы", "теперь", "вместо", "который", "больше", "стали",
            "самый", "модель", "статья", "нейросеть", "искусственный", "интеллект"}
    def words(s):
        return {w for w in re.findall(r"[а-яёa-z0-9]{4,}", s.casefold()) if w not in stop}
    anchor = words(data["title"] + " " + data["summary"])
    scored = []
    for item in catalog.values():
        if not verified(item) or item["dzen_id"] == data.get("dzen_id"):
            continue
        tokens = words(item["title"] + " " + (item.get("excerpt") or "")[:220])
        hits = anchor & tokens
        if len(hits) >= 2:
            scored.append((len(hits), item["title"], item["dzen_id"]))
    return sorted(scored, key=lambda r: (-r[0], r[1]))[:limit]
