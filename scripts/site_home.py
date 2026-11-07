"""Static, indexable homepage selection from articles actually published on iipike.ru."""
from html import escape
import json
from pathlib import Path
import re
from scripts.site_rubrics import RUBRICS, publication_date, publication_date_caps

START = "<!-- HPII_PUBLISHED_SECTION_START -->"
END = "<!-- HPII_PUBLISHED_SECTION_END -->"
FOCUS_START = "<!-- HPII_FOCUS_SECTION_START -->"
FOCUS_END = "<!-- HPII_FOCUS_SECTION_END -->"
FOCUS_PATH = "data/home_focus.json"
ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def sorted_published(records):
    return sorted(records, key=lambda row: (
        row.get("published_at_utc") or row["published"] + "T00:00:00Z", row["id"]
    ), reverse=True)



def load_focus_items(root):
    """Read curated article IDs. No draft, arbitrary URL or external link allowed."""
    path = Path(root) / FOCUS_PATH
    if not path.is_file():
        return []
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ValueError("Unsupported homepage focus config")
    items = config.get("items")
    if not isinstance(items, list) or len(items) not in (0, 4):
        raise ValueError("Homepage focus must contain exactly four rubric picks, or be empty")
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("Invalid homepage focus item")
        sid = item["id"]
        if not ID_PATTERN.fullmatch(sid) or len(sid) > 72 or sid in seen:
            raise ValueError("Invalid or repeated homepage focus ID")
        seen.add(sid)
        if item.get("kind") not in ("hot", "editor"):
            raise ValueError("Homepage focus kind must be hot or editor")
        if not isinstance(item.get("label"), str) or not 1 <= len(item["label"].strip()) <= 28:
            raise ValueError("Invalid homepage focus label")
        if set(item) - {"id", "kind", "label"}:
            raise ValueError("Focus picks are permanent: expiration fields are not allowed")
    return items


def active_focus_ids(records, focus_items):
    by_id = {row["id"]: row for row in records}
    return [item["id"] for item in focus_items
            if item["id"] in by_id and
            by_id[item["id"]].get("url") == "articles/" + item["id"] + "/" and
            by_id[item["id"]].get("cover", "").startswith("assets/")]


def render_focus_section(records, focus_items):
    """Only already published first-party records can appear in curated picks."""
    by_id = {row["id"]: row for row in records}
    cards = []
    for item in focus_items:
        sid = item["id"]
        row = by_id.get(sid)
        if not row or row.get("url") != "articles/" + sid + "/" or not (
                isinstance(row.get("cover"), str) and row["cover"].startswith("assets/")):
            continue
        kind = item["kind"]
        image_load = "eager" if not cards else "lazy"
        cards.append(
            '<a class="home-focus-card home-focus-' + kind + '" href="' +
            escape(row["url"], quote=True) + '">' +
            '<span class="home-focus-image"><img src="' +
            escape(row["cover"], quote=True) +
            '" loading="' + image_load + '" alt="Обложка: ' +
            escape(row["title"], quote=True) + '"></span>' +
            '<span class="home-focus-body">' +
            '<small class="home-focus-tag">' + escape(item["label"]) + '</small>' +
            '<strong class="home-focus-title">' + escape(row["title"]) + '</strong>' +
            '<span class="home-focus-date">' +
            escape(publication_date(row["published"])) + ' · ' +
            escape(RUBRICS[row.get("rubric", "news")]["name"]) +
            '</span></span><span class="home-focus-arrow" aria-hidden="true">↗</span></a>'
        )
    if not cards:
        return ""
    return '''  <section class="home-focus wrap" id="focus" aria-labelledby="home-focus-heading">
    <div class="home-section-head">
      <div><span class="home-section-index">01 / ВЫБОР РЕДАКЦИИ</span><h2 id="home-focus-heading">В фокусе</h2></div>
      <span class="home-focus-note">Не всё важное — самое новое.</span>
    </div>
    <div class="home-focus-grid" data-count="''' + str(len(cards)) + '''">
''' + "\n".join(cards) + '''
    </div>
  </section>'''


def render_home_section(records, focus_items=()):
    """Return current first-party stories, avoiding duplication of pinned items."""
    pinned = set(active_focus_ids(records, focus_items))
    ordered = [row for row in sorted_published(records) if row["id"] not in pinned]
    if not ordered:
        ordered = sorted_published(records)
    if not ordered:
        raise ValueError("At least one published site article is required")
    featured, others = ordered[0], ordered[1:5]
    url = escape(featured["url"], quote=True)
    art = escape(featured["cover"], quote=True)
    title = escape(featured["title"])
    brief = escape(featured["summary"])
    rubric = escape(RUBRICS[featured.get("rubric", "news")]["name"].upper())
    label = escape(publication_date_caps(featured["published"]))
    related = "\n".join(
        '<a class="home-site-post" href="' + escape(row["url"], quote=True) + '">'
        '<img loading="lazy" alt="Обложка статьи" src="' + escape(row["cover"], quote=True) + '">'
        '<span><small class="date">' + escape(publication_date(row["published"]))
        + ' · ' + escape(RUBRICS[row.get("rubric", "news")]["name"]) + '</small>'
        '<h3>' + escape(row["title"]) + '</h3>'
        '<span class="home-site-read">Читать на сайте ↗</span></span></a>'
        for row in others
    )
    count = len(records)
    return f'''  <section class="wrap home-feature" id="archive" aria-labelledby="home-feature-heading">
    <div class="home-section-head home-feature-head">
      <div><span class="home-section-index">02 / НА САЙТЕ</span><h2 id="home-feature-heading">Наши публикации</h2></div>
      <a class="home-text-link" href="articles/">Все {count} материалов <span aria-hidden="true">↗</span></a>
    </div>
    <a class="home-feature-link" href="{url}">
      <div class="home-feature-image">
        <img src="{art}" width="1672" height="941" alt="Обложка: {title}" loading="lazy">
      </div>
      <div class="home-feature-copy">
        <span class="home-section-index">{label} / {rubric}</span>
        <h3>{title}</h3>
        <p>{brief}</p>
        <span class="home-feature-cta">Читать на сайте <span aria-hidden="true">↗</span></span>
      </div>
    </a>
    <div class="home-site-posts" aria-label="Другие материалы на сайте">
{related}
    </div>
    <p class="home-feature-footnote">Свежие статьи из собственного архива ХПИИ. Все материалы доступны прямо на iipike.ru.</p>
  </section>'''


def update_home(existing_html, records, *, root=None):
    """Refresh both indexable editorial picks and latest first-party articles."""
    if root is None:
        root = Path(__file__).resolve().parents[1]
    focus_items = load_focus_items(root)
    if focus_items:
        # Fixed editorial layout: exactly one verified published story per rubric.
        expected_rubrics = ("skynet", "news", "what-are-you-doing", "quotes")
        by_id = {row["id"]: row for row in records}
        for item, rubric in zip(focus_items, expected_rubrics):
            sid = item["id"]
            row = by_id.get(sid)
            if not row or (row.get("rubric") != rubric
                           or row.get("url") != "articles/" + sid + "/"
                           or not isinstance(row.get("cover"), str)
                           or not row["cover"].startswith("assets/")):
                raise ValueError("Focus pick must be a published article of its rubric: " + sid)
            if item["label"] != RUBRICS[rubric]["name"]:
                raise ValueError("Focus pick label must equal its rubric name: " + sid)
    for first, last in ((START, END), (FOCUS_START, FOCUS_END)):
        if existing_html.count(first) != 1 or existing_html.count(last) != 1:
            raise ValueError("Homepage section boundaries must be unique: " + first)
    before, rest = existing_html.split(START, 1)
    _, after = rest.split(END, 1)
    updated = before + START + "\n" + render_home_section(records, focus_items) + "\n" + END + after
    before, rest = updated.split(FOCUS_START, 1)
    _, after = rest.split(FOCUS_END, 1)
    return before + FOCUS_START + "\n" + render_focus_section(records, focus_items) + "\n" + FOCUS_END + after
