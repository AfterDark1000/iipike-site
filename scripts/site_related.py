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
    source_pair = (entry.get("url_evidence"), entry.get("title_evidence"))
    approved_provenance = {
        ("recorded_in_editorial_archive", "recorded"),
        ("verified_on_public_dzen_page", "verified_on_public_dzen_page"),
    }
    if source_pair not in approved_provenance:
        return False
    ident = entry["dzen_id"]
    slug = base64.urlsafe_b64encode(bytes.fromhex(ident)).decode("ascii").rstrip("=")
    return entry.get("dzen_url") == "https://dzen.ru/a/" + slug


def canonical_dzen_url(ident):
    """Produce a URL key for an editor-supplied ID; NOT proof it exists on Dzen."""
    if not isinstance(ident, str) or not ID.fullmatch(ident):
        raise ValueError("Invalid site crosslink Dzen ID")
    slug = base64.urlsafe_b64encode(bytes.fromhex(ident)).decode("ascii").rstrip("=")
    return "https://dzen.ru/a/" + slug


def explicit_site_crosslinks(data, records):
    """Validate approved Dzen-URL -> existing published site-story associations.

    Mapping is used ONLY while rendering the site's HTML. A Dzen ID is
    not evidence the Dzen article exists.
    """
    raw = data.get("site_crosslinks", {})
    if not isinstance(raw, dict) or len(raw) > 4:
        raise ValueError("site_crosslinks must be a map of at most four IDs")
    if not raw:
        return {}
    if data.get("dzen_id"):
        raise ValueError("Historical Dzen imports cannot declare site_crosslinks")
    markdown = data.get("article_markdown")
    if not isinstance(markdown, str):
        raise ValueError("site_crosslinks require verbatim article_markdown")
    related = data.get("related_dzen_ids", [])
    if not isinstance(related, list):
        raise ValueError("site_crosslinks require related_dzen_ids")
    public = {row.get("id"): row for row in records if isinstance(row, dict)}
    mapped = {}
    for ident, target in raw.items():
        url = canonical_dzen_url(ident)
        if ident not in related:
            raise ValueError("site_crosslinks ID missing from related_dzen_ids: " + ident)
        if not isinstance(target, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", target):
            raise ValueError("Invalid site_crosslinks target")
        if target == data.get("id", data.get("slug")):
            raise ValueError("Site crosslink cannot point to its own article")
        row = public.get(target)
        if not row or row.get("url") != "articles/" + target + "/" or not row.get("title"):
            raise ValueError("Site crosslink target is not published: " + target)
        if "](" + url not in markdown:
            raise ValueError("Crosslink absent from approved Dzen Markdown: " + url)
        mapped[ident] = row
    return mapped


def validate_reference(ref, catalog):
    if not isinstance(ref, str) or not ID.fullmatch(ref) or ref == DIARY:
        raise ValueError("Invalid Dzen article reference")
    item = catalog.get(ref)
    if not verified(item):
        raise ValueError("Unverified Dzen article reference: " + ref)
    return item


def validate_links(ids, catalog, current=None, site_crosslinks=None):
    if (not isinstance(ids, list) or len(ids) > 4
            or not all(isinstance(ident, str) for ident in ids)
            or len(ids) != len(set(ids))):
        raise ValueError("Related articles must be a list of up to 4 unique Dzen IDs")
    site_crosslinks = site_crosslinks or {}
    for ident in ids:
        if ident == current:
            raise ValueError("Cannot link article to itself")
        if ident in site_crosslinks:
            # Explicitly verified published site target, not a Dzen claim.
            continue
        validate_reference(ident, catalog)


def render_links(ids, records, catalog, site_crosslinks=None):
    """Prefer an existing iipike.ru article, else link to verified Dzen original."""
    if not ids:
        return ""
    site_crosslinks = site_crosslinks or {}
    local = {}
    for record in records:
        for ident in (record.get("dzen_id"), record.get("site_first_dzen_id")):
            if ident:
                if ident in local and local[ident]["id"] != record.get("id"):
                    raise ValueError("Duplicate Dzen-to-site counterpart link")
                local[ident] = record
    links = []
    for ident in ids:
        if ident in site_crosslinks:
            row = site_crosslinks[ident]
            dest = "../../" + row["url"]
            title = row["title"]
            target = ""
            badge = "На сайте"
        else:
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
