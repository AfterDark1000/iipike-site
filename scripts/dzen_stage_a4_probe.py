"""Evaluate early-comment opportunities from saved, one-page Dzen exports."""

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from dzen_stage_a3_probe import CHANNELS, count, publication_date
from dzen_stage_a_probe import ARTICLE, ORIGIN

AI_TITLE = re.compile(
    r"\b(?:ии|ai|llm|gpt|chatgpt|openai|anthropic|deepseek|claude|gemini|grok|midjourney)\b"
    r"|\b(?:нейросет\w*|нейромодел\w*|нейроагент\w*|"
    r"искусственн\w+\s+интеллект\w*|машинн\w+\s+обучени\w*)\b",
    re.IGNORECASE,
)
PRIORITIES = {"priority_a", "priority_b"}
HISTORY_MIN_HOURS = 24
HISTORY_MAX_HOURS = 7 * 24
MIN_HISTORY = 5
MAX_HISTORY = 10
MAX_CARDS = 25
MAX_SNAPSHOTS = 4


@dataclass(frozen=True)
class Thresholds:
    priority_a_views: int = 1000
    priority_b_views: int = 300
    min_discussed: int = 2
    max_median_gap_hours: int = 48
    max_latest_history_hours: int = 72


@dataclass(frozen=True)
class Article:
    url: str
    title: str
    published_at: datetime
    age_minutes: float
    views: int | None
    comments: int | None
    comments_enabled: bool | None

    @property
    def ai_topic(self):
        return bool(AI_TITLE.search(self.title))


def social_info(card):
    social = card.get("socialInfo")
    return social if isinstance(social, dict) else {}


def metric_total(values):
    totals = {"positive": 0, "zero": 0, "unknown": 0}
    for value in map(count, values):
        key = "unknown" if value is None else "zero" if value == 0 else "positive"
        totals[key] += 1
    return totals


def read_articles(cards, publisher, observed_at):
    articles = {}
    skipped = Counter()
    for card in cards:
        if card.get("item_type") != "native":
            skipped["not_article"] += 1
            continue
        if card.get("publisher_id") != publisher:
            skipped["other_publisher"] += 1
            continue
        url = re.split(r"[?#]", card.get("link") or "", maxsplit=1)[0]
        title = (card.get("title") or "").strip()
        if not ARTICLE.fullmatch(url) or not title:
            skipped["invalid_url_or_title"] += 1
            continue
        published, kind, _ = publication_date(card.get("publication_date"), None)
        if kind != "exact":
            skipped["missing_exact_date"] += 1
            continue
        published_at = datetime.fromisoformat(published)
        age = (observed_at - published_at).total_seconds() / 60
        if age < 0:
            skipped["future_date"] += 1
            continue
        if url in articles:
            skipped["duplicate_url"] += 1
            continue
        social = social_info(card)
        articles[url] = Article(url, title, published_at, age, count(card.get("views")),
                                count(social.get("commentCount")), social.get("commentsEnabled"))
    return sorted(articles.values(), key=lambda article: (article.age_minutes, article.url)), dict(skipped)


def channel_history(articles, thresholds):
    sample = [a for a in articles if HISTORY_MIN_HOURS * 60 <= a.age_minutes <= HISTORY_MAX_HOURS * 60][:MAX_HISTORY]
    views = [a.views for a in sample if a.views is not None]
    comments = [a.comments for a in sample if a.comments is not None]
    discussed = sum(value > 0 for value in comments)
    typical = median(views) if views else None
    gaps = [(older.age_minutes - newer.age_minutes) / 60 for newer, older in zip(sample, sample[1:])]
    gap = median(gaps) if gaps else None
    regular = bool(gap is not None and gap <= thresholds.max_median_gap_hours
                   and sample[0].age_minutes <= thresholds.max_latest_history_hours * 60)
    if min(len(views), len(comments)) < MIN_HISTORY:
        status = "insufficient_evidence"
    elif not regular or discussed < thresholds.min_discussed or typical < thresholds.priority_b_views:
        status = "low_activity"
    elif typical >= thresholds.priority_a_views:
        status = "priority_a"
    else:
        status = "priority_b"
    return {
        "status": status,
        "channel_history_sample_size": len(sample),
        "channel_historical_median_views": typical,
        "channel_history_discussion_rate": round(discussed / len(comments), 4) if comments else None,
        "views_known": len(views),
        "comments_known": len(comments),
        "articles_with_discussion": discussed,
        "history_ai_articles": sum(a.ai_topic for a in sample),
        "median_gap_hours": round(gap, 2) if gap is not None else None,
        "sample_age_hours": [round(sample[0].age_minutes / 60, 2),
                             round(sample[-1].age_minutes / 60, 2)] if sample else None,
        "regular_in_sample": regular,
    }


def article_window(article):
    if not article.ai_topic:
        return "off_topic"
    if article.age_minutes > 120:
        return "older_than_120_minutes"
    if article.comments_enabled is not True:
        return "comments_closed_or_unconfirmed"
    if article.comments is None:
        return "unknown_comment_count"
    if article.comments > 10:
        return "too_many_comments"
    if article.age_minutes <= 60 and article.comments <= 3:
        return "first_30_minutes" if article.age_minutes <= 30 else "first_60_minutes"
    return "fallback"


EARLY_WINDOWS = {"first_30_minutes", "first_60_minutes", "fallback"}


def article_record(article, window, slug, source, observed_at, history):
    return {
        "title": article.title,
        "url": article.url,
        "channel": slug,
        "source": source,
        "source_type": "dzen_channel_export",
        "observed_at": observed_at,
        "published_at": article.published_at.isoformat(),
        "first_seen_at": observed_at,
        "article_age_minutes": article.age_minutes,
        "current_article_comments": article.comments,
        "current_article_views": article.views,
        "window": window,
        "channel_status": history["status"],
        **{key: value for key, value in history.items() if key.startswith("channel_")},
    }


def analyze_snapshot(slug, data, observed_at, thresholds):
    channel = data["channel"]
    source = channel["source"]
    publisher = source["publisher_id"]
    cards = data["items"]
    if (channel["status"] != "ok" or not re.fullmatch(r"[a-f0-9]{24}", publisher)
            or dict(CHANNELS).get(slug, publisher) != publisher
            or re.split(r"[?#]", source["feed_link"], maxsplit=1)[0] != f"{ORIGIN}/{slug}"
            or not isinstance(cards, list) or len(cards) > MAX_CARDS
            or not all(isinstance(card, dict) for card in cards)):
        raise ValueError(f"Unexpected one-page export for {slug}")

    articles, skipped = read_articles(cards, publisher, observed_at)
    history = channel_history(articles, thresholds)
    source_url = f"{ORIGIN}/api/v3/launcher/export?channel_name={slug}"
    observed = observed_at.isoformat()
    filters = Counter(article_window(article) for article in articles)
    early = [article_record(a, window, slug, source_url, observed, history)
             for a in articles if (window := article_window(a)) in EARLY_WINDOWS]
    newest_ai = next((a for a in articles if a.ai_topic and a.age_minutes <= 72 * 60), None)
    return {
        "channel": slug,
        "title": source["title"],
        "subscribers": count(source.get("subscribers")),
        "source": source_url,
        "source_type": "dzen_channel_export",
        "observed_at": observed,
        "all_cards": {
            "total": len(cards),
            "types": dict(Counter(card.get("item_type", "unknown") for card in cards)),
            "views": metric_total(card.get("views") for card in cards),
            "comments": metric_total(social_info(card).get("commentCount") for card in cards),
        },
        "valid_articles": len(articles),
        "skipped_cards": skipped,
        "article_filters": dict(filters),
        "freshness": {
            "all_articles_up_to_30_minutes": sum(a.age_minutes <= 30 for a in articles),
            "all_articles_up_to_60_minutes": sum(a.age_minutes <= 60 for a in articles),
            "all_articles_up_to_120_minutes": sum(a.age_minutes <= 120 for a in articles),
            "ai_articles_up_to_72_hours": sum(a.ai_topic and a.age_minutes <= 72 * 60 for a in articles),
        },
        "history": history,
        "newest_ai_up_to_72_hours": article_record(newest_ai, article_window(newest_ai), slug, source_url,
                                                   observed, history) if newest_ai else None,
    }, early


def story_words(title):
    return set(re.findall(r"\b\w{4,}\b", title.casefold().replace("ё", "е")))


def evaluate(snapshots, thresholds):
    channels, early = [], []
    for slug, data, observed in snapshots:
        channel, articles = analyze_snapshot(slug, data, observed, thresholds)
        channels.append(channel)
        early.extend(articles)

    # Prefer the main list when two channels cover the same story.
    window_order = {"first_30_minutes": 0, "first_60_minutes": 1, "fallback": 2}
    early.sort(key=lambda a: (a["channel_status"] not in PRIORITIES, window_order[a["window"]],
                              a["article_age_minutes"], a["current_article_comments"], a["url"]))
    opportunities, unqualified, seen = [], [], []
    for article in early:
        words = story_words(article["title"])
        if any(article["title"].casefold() == prior["title"].casefold()
               or (len(words & previous) >= 4 and len(words & previous) / len(words | previous) >= 0.6)
               for prior, previous in seen):
            continue
        seen.append((article, words))
        target = opportunities if article["channel_status"] in PRIORITIES else unqualified
        target.append(article)

    total = len(opportunities)
    within_30 = sum(a["article_age_minutes"] <= 30 for a in opportunities)
    within_60 = sum(a["article_age_minutes"] <= 60 for a in opportunities)
    return {
        "thresholds": vars(thresholds),
        "channels": channels,
        "article_only_matches_before_story_dedup": len(early),
        "duplicate_stories": len(early) - len(seen),
        "opportunities": opportunities,
        "unqualified_candidates": unqualified,
        "qualified_candidate_timing": {
            "total": total,
            "within_30_minutes": within_30,
            "within_60_minutes": within_60,
            "rate_30_minutes": round(within_30 / total, 4) if total else None,
            "rate_60_minutes": round(within_60 / total, 4) if total else None,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", nargs=3, metavar=("SLUG", "OBSERVED_AT", "FILE"),
                        action="append", required=True)
    parser.add_argument("--priority-a-views", type=int, default=1000)
    parser.add_argument("--priority-b-views", type=int, default=300)
    args = parser.parse_args()
    if not 0 < args.priority_b_views <= args.priority_a_views:
        parser.error("Expected 0 < priority B views <= priority A views")
    if len(args.snapshot) > MAX_SNAPSHOTS or len({row[0] for row in args.snapshot}) != len(args.snapshot):
        parser.error("Expected at most four distinct channel snapshots")
    snapshots = []
    try:
        for slug, when, file in args.snapshot:
            observed_at = datetime.fromisoformat(when)
            if observed_at.tzinfo is None or not re.fullmatch(r"[a-zA-Z0-9_.-]+", slug):
                raise ValueError("Expected a channel slug and ISO timestamp with timezone")
            snapshots.append((slug, json.loads(Path(file).read_bytes()), observed_at.astimezone(UTC)))
        result = evaluate(snapshots, Thresholds(args.priority_a_views, args.priority_b_views))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
