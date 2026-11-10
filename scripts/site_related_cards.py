"""Conservative site-only related cards.

Approved Markdown remains the one unchanged Dzen article. The HTML publisher
may remove exactly one mapped inline anchor from the displayed paragraph and
place a card after that paragraph, or choose a rare, topic-grounded fallback.
Historical Dzen imports remain unchanged.
"""
from collections import Counter
from datetime import date
from html import escape
import re
from urllib.parse import urlsplit

BASE = "https://iipike.ru"
LINK = re.compile(r"\[([^\]\n]{1,200})\]\((https://[^)\n]{1,2000})\)")
SLUG = re.compile(r"articles/([a-z0-9]+(?:-[a-z0-9]+)*)/\Z")
COVER = re.compile(r"assets/[a-z0-9][a-z0-9/_-]*\.(?:webp|png|jpg|jpeg)\Z")
ENTITY = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]*(?:[-.][A-Za-z0-9]+)*(?![A-Za-z0-9])")
STOP = frozenset({
    "AI", "API", "LLM", "GPT", "TPU", "GPU", "CPU", "SDK", "SQL", "PDF", "RSS",
    "HTML", "CSS", "HTTP", "HTTPS", "URL", "USA", "US", "UK", "CEO", "CFO",
    "META", "GOOGLE", "OPENAI", "ANTHROPIC", "NVIDIA", "MICROSOFT", "APPLE",
    "AMAZON", "CLAUDE", "CHATGPT", "GEMINI", "GROK", "AGENT", "AGENTS",
    "GITHUB", "LINUX", "ANDROID", "WINDOWS", "PYTHON", "DISNEY",
})
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря"]
RUBRIC_LABELS = {
    "news": "Новости ИИ", "skynet": "Скайнет просыпается",
    "what-are-you-doing": "ИИ, ты чего творишь?", "quotes": "Громко сказано",
}


def _public_rows(records, current_id):
    """Only known published same-site pages with usable covers may appear."""
    rows = {}
    for row in records:
        path = row.get("url", "")
        if (not isinstance(path, str) or not SLUG.fullmatch(path)
                or row.get("id") == current_id
                or path != "articles/" + str(row.get("id")) + "/"
                or not isinstance(row.get("title"), str) or not row["title"]
                or not isinstance(row.get("cover"), str)
                or not COVER.fullmatch(row["cover"])
                or not isinstance(row.get("published"), str)):
            continue
        try:
            date.fromisoformat(row["published"])
        except ValueError:
            continue
        rows[BASE + "/" + path] = row
    return rows


def _target(url, site_links, public):
    """Resolve already verified Dzen -> site mappings, never guess a Dzen URL."""
    parsed = urlsplit(url)
    if parsed.hostname == "dzen.ru" and parsed.scheme == "https":
        mapped = site_links.get("https://dzen.ru" + parsed.path.rstrip("/"))
        return public.get(mapped) if mapped else None
    if parsed.scheme == "https" and parsed.hostname == "iipike.ru":
        # Accept only the precise published article path, not a tracking URL.
        return public.get("https://iipike.ru" + parsed.path)
    return None


def _entities(text):
    """Distinctive product/project names; company names alone are insufficient."""
    result = set()
    for match in ENTITY.finditer(text):
        token = match.group(0)
        value = token.upper()
        # An entity has a capital, and is specific enough to avoid prose words.
        if (len(token) >= 5 and token[0].isupper()
                and value not in STOP and not value.isdigit()):
            result.add(value)
    return result


def _related_fallback(data, blocks, records, public):
    """Choose at most one credible previously published match; fail closed."""
    own_topics = set(data.get("topics") or [])
    if not own_topics:
        return None
    own_day = data.get("published", "")
    text = " ".join(
        b.get("text", "") for b in blocks
        if b["type"] in ("lead", "p", "h2", "h3")
    )
    own_entities = _entities(text)
    if not own_entities:
        return None
    frequency = Counter()
    for row in public.values():
        frequency.update(_entities(row["title"]))
    candidates = []
    for row in public.values():
        if row["published"] > own_day:
            continue
        topic_overlap = own_topics.intersection(row.get("topics") or [])
        if not topic_overlap:
            continue
        shared = own_entities.intersection(_entities(row["title"]))
        # A product/entity seen across the whole front page is not an
        # editorial relationship. Require a rare project name in the headline.
        rare = [x for x in shared if 1 <= frequency[x] <= 6]
        if not rare:
            continue
        best = min(frequency[x] for x in rare)
        score = (len(rare), -best, row["published"], row["id"])
        candidates.append((score, row, sorted(rare)))
    if not candidates:
        return None
    _, row, rare = max(candidates, key=lambda x: x[0])
    # Put the card after an explanatory paragraph mentioning the same entity,
    # not in a heading, citation or opening lead.
    positions = []
    for i, block in enumerate(blocks):
        if i < 2 or block["type"] != "p":
            continue
        if _entities(block.get("text", "")).intersection(rare):
            positions.append(i)
    if not positions:
        return None
    # Prefer a middle paragraph while keeping the card near the relevant fact.
    desired = max(2, int(len(blocks) * .55))
    position = min(positions, key=lambda i: (abs(i - desired), i))
    return row, position


def site_card_html(row):
    """HTML is escaped and only uses a published record's canonical URL."""
    title = escape(row["title"], quote=True)
    url = escape(BASE + "/" + row["url"], quote=True)
    cover = escape("../../" + row["cover"], quote=True)
    day = date.fromisoformat(row["published"])
    date_label = f"{day.day} {MONTHS[day.month - 1]} {day.year}"
    label = RUBRIC_LABELS.get(row.get("rubric"), "Материал")
    return (
        '<a class="editorial-related-card" href="' + url +
        '" aria-label="По теме: ' + title + '">'
        '<img loading="lazy" decoding="async" src="' + cover + '" alt="">'
        '<span class="editorial-related-card-copy">'
        '<span class="editorial-related-card-eyebrow">По теме</span>'
        '<span class="editorial-related-card-title">' + title + '</span>'
        '<span class="editorial-related-card-meta">' +
        escape(label) + ' · ' + date_label + '</span>'
        '</span></a>'
    )


def select_site_card(data, blocks, records, site_links):
    """Return (render-only blocks, after-block HTML, chosen published row).

    A verified inline link beats any inferred recommendation.
    Dzen text and metadata are never mutated.
    """
    if data.get("dzen_id"):
        return blocks, {}, None
    public = _public_rows(records, data.get("id", data.get("slug")))
    # First editorial reference inside a normal body paragraph takes priority.
    for i, block in enumerate(blocks):
        if i < 1 or block["type"] != "p":
            continue
        original = block["text"]
        for match in LINK.finditer(original):
            row = _target(match.group(2), site_links, public)
            if row is None:
                continue
            replaced = original[:match.start()] + match.group(1) + original[match.end():]
            modified = list(blocks)
            modified[i] = dict(block, text=replaced)
            return modified, {i: site_card_html(row)}, row
    related = _related_fallback(data, blocks, records, public)
    if related:
        row, position = related
        return blocks, {position: site_card_html(row)}, row
    return blocks, {}, None


def remove_duplicate_related_ids(ids, card_row, explicit_mappings):
    """Keep other bottom links, but suppress a duplicate of the card."""
    if not card_row:
        return ids
    own_ids = {card_row.get("dzen_id"), card_row.get("site_first_dzen_id")}
    own_ids.discard(None)
    own_ids.update(ident for ident, row in explicit_mappings.items()
                   if row.get("id") == card_row["id"])
    return [ident for ident in ids if ident not in own_ids]
