"""Safe, data-only extensions to the HPII topical vocabulary.

The working editor can register a recurring topic by appending one reviewed
JSON record and merging a green PR. No Python source edits are needed.
Evidence is editorial audit data, never shown to readers; it does not replace
semantic source review by the editor.
"""
import difflib
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit

TOPIC_KEY = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
ARTICLE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
ALLOWED_ENTRY = {"key", "name", "description", "why_not_existing", "evidence"}
ALLOWED_EVIDENCE = {"article_id", "source_url"}
_EMPTY = {"schema_version": 1, "topics": []}


def _normalized_name(name):
    name = unicodedata.normalize("NFKC", name).casefold().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", name)


def _text(value, field, minimum, maximum):
    if (not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum
            or value != value.strip() or any(ord(c) < 32 for c in value)):
        raise ValueError("Invalid " + field)
    return value


def _valid_evidence(evidence, known_article_ids):
    if not isinstance(evidence, list) or not 2 <= len(evidence) <= 6:
        raise ValueError("A new topic needs two to six independent examples")
    unique = set()
    for item in evidence:
        if not isinstance(item, dict) or len(item) != 1 or set(item) - ALLOWED_EVIDENCE:
            raise ValueError("Evidence must be a published article ID or original HTTPS source")
        if "article_id" in item:
            value = item["article_id"]
            if (not isinstance(value, str) or not ARTICLE_ID.fullmatch(value)
                    or len(value) > 100 or value not in known_article_ids):
                raise ValueError("Evidence article ID does not exist in the published site index")
            identity = "article:" + value
        else:
            value = item["source_url"]
            _text(value, "evidence source URL", 15, 2048)
            parts = urlsplit(value)
            try:
                safe_port = parts.port in (None, 443)
            except ValueError:
                safe_port = False
            if (parts.scheme != "https" or not parts.hostname or parts.username or
                    parts.password or not safe_port or
                    any(c.isspace() for c in value)):
                raise ValueError("Evidence source needs a safe HTTPS URL")
            identity = "source:" + value.rstrip("/").casefold()
        if identity in unique:
            raise ValueError("Repeated topic evidence does not establish recurrence")
        unique.add(identity)


def validate_manifest(manifest, base_topics, known_article_ids):
    if (not isinstance(manifest, dict) or set(manifest) != {"schema_version", "topics"}
            or manifest["schema_version"] != 1
            or not isinstance(manifest["topics"], list)):
        raise ValueError("Topic extensions must use the approved schema_version 1")
    known = set(base_topics)
    names = {_normalized_name(name): key for key, (name, _) in base_topics.items()}
    results = {}
    for entry in manifest["topics"]:
        if not isinstance(entry, dict) or set(entry) != ALLOWED_ENTRY:
            raise ValueError("Topic entry must contain all five approved fields only")
        key = entry["key"]
        if (not isinstance(key, str) or len(key) > 48 or
                not TOPIC_KEY.fullmatch(key) or key in known):
            raise ValueError("Topic key is unsafe or already registered")
        name = _text(entry["name"], "topic name", 4, 65)
        desc = _text(entry["description"], "topic description", 35, 240)
        why = _text(entry["why_not_existing"], "topic distinction", 40, 700)
        norm = _normalized_name(name)
        if norm in names:
            raise ValueError("Topic name duplicates an existing name: " + names[norm])
        # Reject near-identical spelling, not merely shared concepts/words.
        # Semantic duplicates need the editor's judgment and archive review.
        for other, existing_key in names.items():
            if difflib.SequenceMatcher(None, norm, other).ratio() >= 0.94:
                raise ValueError("Topic name is confusingly close to " + existing_key)
        _valid_evidence(entry["evidence"], known_article_ids)
        known.add(key)
        names[norm] = key
        results[key] = (name, desc)
    return results


def load_manifest(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("Topic registry file missing or unsafe")
    if path.stat().st_size > 256_000:
        raise ValueError("Topic registry exceeds safe size limit")
    return json.loads(path.read_text(encoding="utf-8"))


def load_extensions(path, base_topics, published_index):
    raw = load_manifest(path)
    index_path = Path(published_index)
    if not index_path.is_file() or index_path.is_symlink():
        raise ValueError("Verified publication index missing")
    rows = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Invalid publication index")
    known_article_ids = {row["id"] for row in rows}
    return validate_manifest(raw, base_topics, known_article_ids)


def require_append_only(old, new):
    """No silent topic rename, deletion, semantic retcon or URL break."""
    if (not isinstance(old, dict) or not isinstance(new, dict) or
            old.get("schema_version") != 1 or new.get("schema_version") != 1 or
            not isinstance(old.get("topics"), list) or
            not isinstance(new.get("topics"), list)):
        raise ValueError("Invalid topic manifest revision")
    original = old["topics"]
    if new["topics"][:len(original)] != original:
        raise ValueError("Topic registry must be append-only: existing topics are permanent")
    return len(new["topics"]) - len(original)
