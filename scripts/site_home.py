"""Static, indexable homepage selection from articles actually published on iipike.ru."""
from html import escape
from scripts.site_rubrics import RUBRICS, publication_date, publication_date_caps

START = "<!-- HPII_PUBLISHED_SECTION_START -->"
END = "<!-- HPII_PUBLISHED_SECTION_END -->"


def sorted_published(records):
    return sorted(records, key=lambda row: (
        row.get("published_at_utc") or row["published"] + "T00:00:00Z", row["id"]
    ), reverse=True)


def render_home_section(records):
    """Return server-rendered links; do not rely on JS for search crawlers."""
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
    <p class="home-feature-footnote">Полные статьи с обложками, первоисточниками и оригинальными датами публикаций в Дзене. Все материалы доступны прямо на iipike.ru.</p>
  </section>'''


def update_home(existing_html, records):
    """Replace one marked homepage fragment, preserving the rest unchanged."""
    if existing_html.count(START) != 1 or existing_html.count(END) != 1:
        raise ValueError("Homepage article section boundaries must be unique")
    before, rest = existing_html.split(START, 1)
    _, after = rest.split(END, 1)
    return before + START + "\n" + render_home_section(records) + "\n" + END + after
