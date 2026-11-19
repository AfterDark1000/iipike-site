"""Read existing commenting and pilot snapshots without contacting their sources."""

import json

from commenting_queue import PUBLISHER_HOSTS, allowed_url, date, dzen_url
from dzen_first_car import HOUR, MAX_COMMENTS, canonical, iso, timestamp


def publisher_candidates(data, as_of, window):
    observed = date(data["updated_at"])
    if observed is None:
        raise ValueError("Missing time on the commenting queue snapshot")
    seen = int(observed.timestamp())
    if as_of < seen:
        return
    sources = {source["id"] for source in data["sources"]}
    for article in data["items"]:
        published = date(article.get("published_at"))
        comment = article.get("comment")
        if (article.get("source_id") not in sources or article.get("status") != "draft_ready"
                or not isinstance(comment, str) or not comment.strip() or published is None
                or not 0 <= as_of - int(published.timestamp()) <= window):
            continue
        try:
            original = allowed_url(article["source_url"], PUBLISHER_HOSTS)
        except ValueError:
            continue
        mirror = dzen_url(article.get("dzen_url"))
        yield {
            "kind": "publisher", "title": article["title"], "source_name": article["source_name"],
            "source_url": original, "dzen_url": mirror, "observed_at": iso(seen),
            "publisher_published_at": published.isoformat(), "dzen_published_at": None,
            "comments": None, "comments_open": None, "views": None, "confidence": "publisher_only",
            "draft_comment": comment, "reason": "Статья сайта издателя. " + (
                "Зеркало указано в очереди издателя. Время и обсуждение Дзена не сверены." if mirror
                else "Ссылка на версию Дзена неизвестна."),
        }


def pilot_candidates(data, as_of, window):
    for channel in data["channels"]:
        history = next((band for band in channel["age_cohorts_hours"] if band["enough_for_comparison"]), None)
        for article in channel["ai_observations"]:
            seen = timestamp(article["observed_at"])
            published = timestamp(article["published_at"])
            comments = article["comments"]
            if (not published <= seen <= as_of or as_of - published > window
                    or article["comments_open"] is False or (comments is not None and comments > MAX_COMMENTS)):
                continue
            yield {
                **article, "kind": "dzen", "dzen_url": canonical(article["url"]),
                "dzen_published_at": article["published_at"], "source_name": channel["publisher_title"],
                "historical": True, "history": history, "confidence": "limited",
                "reason": channel["status_reason"] + " Счётчики отражают разовый снимок.",
            }


def candidate_order(row, as_of):
    published = date(row.get("dzen_published_at") or row.get("publisher_published_at"))
    age = as_of - int(published.timestamp())
    band = 0 if age < 2 * HOUR else 1 if age < 8 * HOUR else 2 if age <= 24 * HOUR else 3
    comments = row.get("comments")
    tier = 2 if comments is None else int(comments > 3)
    return band, tier, age, row["key"]


class SavedCandidates:
    def __init__(self, commenting_path=None, pilot_path=None):
        self.commenting = json.loads(commenting_path.read_bytes()) if commenting_path else None
        self.pilot = json.loads(pilot_path.read_bytes()) if pilot_path else None
        if self.commenting is not None and self.commenting["schema_version"] != 1:
            raise ValueError("Unsupported commenting queue schema")

    def add_to(self, snapshot, as_of, window):
        verified = {article["url"]: article for article in snapshot["articles"]}
        candidates = {}
        native = snapshot["candidates"]
        if self.pilot is not None:
            native = [*native, *pilot_candidates(self.pilot, as_of, window)]
        for row in native:
            key = row["dzen_url"]
            if key not in verified:
                candidates.setdefault(key, {**row, "key": key})
        if self.commenting is not None:
            for row in publisher_candidates(self.commenting, as_of, window):
                key = row["dzen_url"] or row["source_url"]
                companion = verified.get(key) or candidates.get(key)
                if companion is None:
                    candidates[key] = {**row, "key": key}
                elif not companion.get("draft_comment"):
                    companion.update({field: row[field] for field in (
                        "draft_comment", "source_url", "publisher_published_at",
                    )})
        snapshot["candidates"] = sorted(candidates.values(), key=lambda row: candidate_order(row, as_of))
