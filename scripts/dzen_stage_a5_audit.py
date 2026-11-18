"""Audit saved Dzen article counters and shortlist channels from public catalog HTML."""

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from dzen_stage_a3_probe import count
from dzen_stage_a4_probe import AI_TITLE, EARLY_WINDOWS, MAX_SNAPSHOTS, article_window, export_cards, read_articles

AGE_BANDS = ((24, 48), (48, 72), (72, 168))
MIN_COHORT = 5
AI_CONTEXT = re.compile(
    r"генерац|обучен|модел|алгоритм|промпт|ассистент|агент|чат[- ]бот|генератив|релиз|запустил|разработ",
    re.IGNORECASE,
)
AI_TAGS = {"искусственный интеллект", "нейросети", "машинное обучение", "artificial intelligence", "generative ai"}
SLUG = re.compile(r"(?:[a-zA-Z0-9_.-]+|id/[a-f0-9]{24})")
FLIGHT = re.compile(r"<script>self\.__next_f\.push\(([^\r\n]*?)\)</script>")
METRIC_STATUS = "metric_definition_unverified"


def topic_basis(title, excerpt="", tags=()):
    if AI_TITLE.search(title):
        return "title"
    sentences = re.split(r"(?<=[.!?])\s+", excerpt.strip()[:300], maxsplit=2)
    if any(AI_TITLE.search(sentence) and AI_CONTEXT.search(sentence) for sentence in sentences[:2]):
        return "excerpt"
    if AI_TITLE.search(excerpt[:300]) and set(tags) & AI_TAGS:
        return "excerpt_and_tag"
    return None


def article_topics(cards):
    topics = {}
    for card in cards:
        url = re.split(r"[?#]", card.get("link") or "", maxsplit=1)[0]
        excerpt = card.get("text")
        excerpt = excerpt if isinstance(excerpt, str) else ""
        interests = card.get("interests")
        interests = interests if isinstance(interests, list) else []
        tags = [str(tag.get("title") or tag.get("name") or "").casefold().strip()
                for tag in interests if isinstance(tag, dict)]
        if card.get("item_type") == "native":
            topics.setdefault(url, topic_basis(card.get("title") or "", excerpt, tags))
    return topics


def age_cohorts(articles):
    result = []
    for lower, upper in AGE_BANDS:
        sample = [a for a in articles if lower <= a.age_minutes / 60 < upper]
        views = [a.views for a in sample if a.views is not None]
        comments = [a.comments for a in sample if a.comments is not None]
        discussed = sum(value > 0 for value in comments)
        result.append({
            "age_hours": [lower, upper],
            "sample_size": len(sample),
            "views_known": len(views),
            "comments_known": len(comments),
            "median_views": median(views) if views else None,
            "discussed": discussed,
            "discussion_rate": round(discussed / len(comments), 4) if comments else None,
            "enough_for_comparison": min(len(views), len(comments)) >= MIN_COHORT,
        })
    return result


def audit_snapshot(slug, data, observed_at):
    source, cards = export_cards(slug, data)
    publisher = source["publisher_id"]
    articles, _ = read_articles(cards, publisher, observed_at)
    # The same publisher restriction governs titles, excerpts, and counters.
    topics = article_topics([card for card in cards if card.get("publisher_id") == publisher])
    cohort_data = age_cohorts(articles)
    oldest = articles[-1].age_minutes / 60 if articles else None
    mature = [a for a in articles if 24 <= a.age_minutes / 60 < 168]
    latest = articles[:10]
    ai_latest = [a for a in latest if topics.get(a.url)]
    ai_discussed = sum(bool(topics.get(a.url) and a.comments) for a in mature)
    gaps = [(b.age_minutes - a.age_minutes) / 60 for a, b in zip(mature, mature[1:])]
    typical_gap = median(gaps) if gaps else None
    contextual = [a for a in articles if topics.get(a.url) in {"excerpt", "excerpt_and_tag"}]
    early = [
        {
            "url": a.url,
            "title": a.title,
            "topic_basis": topics[a.url],
            "window": window,
            "published_at": a.published_at.isoformat(),
            "first_seen_at": observed_at.isoformat(),
            "comments": a.comments,
            "views": a.views,
        }
        for a in articles
        if (window := article_window(a, ai_topic=bool(topics.get(a.url)))) in EARLY_WINDOWS
    ]
    if oldest is not None and oldest < 24:
        coverage = "recent_page_only"
    elif any(c["enough_for_comparison"] for c in cohort_data):
        coverage = "comparable_sample"
    else:
        coverage = "insufficient_evidence"
    return {
        "channel": slug,
        "title": source["title"],
        "source": f"https://dzen.ru/api/v3/launcher/export?channel_name={slug}",
        "observed_at": observed_at.isoformat(),
        "metric_status": METRIC_STATUS,
        "audience_status": METRIC_STATUS if coverage == "comparable_sample" else "insufficient_evidence",
        "articles": len(articles),
        "oldest_article_age_hours": round(oldest, 3) if oldest is not None else None,
        "newest_article_age_hours": round(articles[0].age_minutes / 60, 3) if articles else None,
        "coverage": coverage,
        "cohorts": cohort_data,
        "latest_topic_sample_size": len(latest),
        "ai_in_latest_topic_sample": len(ai_latest),
        "mature_ai_articles_with_discussion": ai_discussed,
        "mature_median_gap_hours": round(typical_gap, 3) if typical_gap is not None else None,
        "regular_in_sample": bool(typical_gap is not None and typical_gap <= 48
                                  and mature[0].age_minutes <= 72 * 60),
        "contextual_topic_matches": len(contextual),
        "contextual_examples": [{"url": a.url, "title": a.title, "basis": topics[a.url]} for a in contextual[:2]],
        "early_article_only_matches": early,
    }


def catalog_rows(html):
    decoder = json.JSONDecoder()
    for match in FLIGHT.finditer(html):
        if "initialData" not in match[1]:
            continue
        packet = json.loads(match[1])
        if not (isinstance(packet, list) and len(packet) == 2 and isinstance(packet[1], str)):
            continue
        _, marker, payload = packet[1].partition('"initialData":')
        if marker:
            data, _ = decoder.raw_decode(payload.lstrip())
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                return data["items"]
    raise ValueError("Public catalog rows were not present in the saved HTML")


def shortlist(sources, audits):
    history = {audit["channel"]: audit for audit in audits}
    results = {}
    for url, rows in sources:
        for row in rows:
            slug = row.get("slug")
            if not isinstance(slug, str) or not SLUG.fullmatch(slug) or slug in results:
                continue
            title = row.get("title") or ""
            topic_hint = bool(AI_TITLE.search(title + " " + (row.get("description") or "")[:500]))
            publications = count(row.get("publications30days"))
            views = count(row.get("views30days"))
            audit = history.get(slug)
            if not (topic_hint or (audit and audit["ai_in_latest_topic_sample"] >= 2)):
                continue
            if publications is None or publications < 4 or not views:
                continue
            if audit:
                total = audit["latest_topic_sample_size"]
                topical = audit["ai_in_latest_topic_sample"]
                if total >= 5 and (topical < 2 or topical * 4 < total):
                    continue
            discussions = audit["mature_ai_articles_with_discussion"] if audit else None
            provisional = discussions is not None and discussions >= 2 and audit["regular_in_sample"]
            results[slug] = {
                "channel": slug,
                "title": title,
                "catalog_source": url,
                "catalog_publications_30d": publications,
                "catalog_views_30d": views,
                "catalog_views_observed_days": count(row.get("viewsObservedDays")),
                "catalog_views_estimated": row.get("views30daysEstimated"),
                "mature_ai_articles_with_discussion": discussions,
                "status": "topic_and_discussion_observed" if provisional else "needs_article_evidence",
                "audience_status": audit["audience_status"] if audit else "insufficient_evidence",
            }
    ranked = sorted(results.values(), key=lambda row: (
        row["status"] != "topic_and_discussion_observed",
        row["catalog_views_estimated"] is not False,
        -(row["catalog_views_observed_days"] or 0),
        -row["catalog_views_30d"],
        row["channel"],
    ))
    return {"matching_catalog_candidates": len(ranked), "shortlist": ranked[:6]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", nargs=3, metavar=("SLUG", "OBSERVED_AT", "FILE"), action="append", default=[])
    parser.add_argument("--catalog", nargs=2, metavar=("PUBLIC_URL", "HTML_FILE"), action="append", default=[])
    args = parser.parse_args()
    if not args.snapshot and not args.catalog:
        parser.error("Expected at least one saved input")
    if len(args.snapshot) > MAX_SNAPSHOTS or len({s[0] for s in args.snapshot}) != len(args.snapshot) or len(args.catalog) > 2:
        parser.error("Expected up to four distinct channel snapshots and two saved catalog pages")
    try:
        audits = []
        for slug, when, file in args.snapshot:
            observed = datetime.fromisoformat(when)
            if observed.tzinfo is None or not SLUG.fullmatch(slug):
                raise ValueError("Expected a channel slug and ISO timestamp with timezone")
            audits.append(audit_snapshot(slug, json.loads(Path(file).read_bytes()), observed.astimezone(UTC)))
        sources = [(url, catalog_rows(Path(file).read_text(encoding="utf-8"))) for url, file in args.catalog]
        result = {"channels": audits, "catalog": shortlist(sources, audits)}
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
