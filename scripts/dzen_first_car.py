"""Offline ingestion, durable history, and snapshots for the Dzen first-car queue."""

import argparse
import json
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from dzen_stage_a3_probe import count, publication_date
from dzen_stage_a5_audit import SLUG, topic_basis
from dzen_stage_a_probe import ARTICLE, ORIGIN

BANDS = ((24, 48), (48, 72), (72, 168))
HOUR = 3600
FRESHNESS = 900
WINDOW = 3600
MIN_SAMPLE = 5
MIN_MEDIAN = 300
EDITORIAL_TIMEZONE = timezone(timedelta(hours=5))
POLICIES = {"unverified", "approved", "fixture"}
ACTIONS = {"commented", "skipped", "undo"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS channels(slug TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS articles(
    url TEXT PRIMARY KEY, channel TEXT NOT NULL REFERENCES channels(slug),
    published INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS observations(
    url TEXT NOT NULL REFERENCES articles(url), seen INTEGER NOT NULL,
    title TEXT NOT NULL, ai INTEGER, views INTEGER, comments INTEGER,
    comments_open INTEGER, source TEXT NOT NULL, policy TEXT NOT NULL,
    verified INTEGER NOT NULL, permission_ref TEXT,
    PRIMARY KEY(url, seen)
);
CREATE TABLE IF NOT EXISTS snapshots(
    channel TEXT NOT NULL REFERENCES channels(slug), seen INTEGER NOT NULL,
    urls TEXT NOT NULL, PRIMARY KEY(channel, seen)
);
CREATE INDEX IF NOT EXISTS snapshots_seen ON snapshots(seen);
CREATE TABLE IF NOT EXISTS offers(
    url TEXT PRIMARY KEY REFERENCES articles(url), offered INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions(
    id INTEGER PRIMARY KEY, url TEXT NOT NULL REFERENCES offers(url), action TEXT NOT NULL,
    recorded INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS decisions_as_of ON decisions(url, recorded DESC, id DESC);
CREATE TABLE IF NOT EXISTS scout_signals(
    url TEXT PRIMARY KEY, detected INTEGER NOT NULL, title TEXT NOT NULL,
    source_url TEXT NOT NULL, policy TEXT NOT NULL, permission_ref TEXT,
    action TEXT, marked INTEGER
);
CREATE INDEX IF NOT EXISTS scout_signals_detected ON scout_signals(detected);
"""


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})", value):
        raise ValueError("Expected ISO timestamp with seconds and timezone")
    return int(datetime.fromisoformat(value).timestamp())


def iso(value):
    return datetime.fromtimestamp(value, UTC).isoformat() if value is not None else None


def canonical(url):
    if not isinstance(url, str) or not ARTICLE.fullmatch(clean := re.split(r"[?#]", url, 1)[0]):
        raise ValueError("Expected a direct Dzen article URL")
    return clean


def boolean(value):
    if value is not None and type(value) is not bool:
        raise ValueError("Expected boolean or null")
    return value


def counter(value):
    if value is not None and count(value) is None:
        raise ValueError("Expected a nonnegative integer or null")
    return value


def label(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError("Expected a nonempty label of up to 500 characters")
    return value.strip()


def connect(path, *, replay=False):
    db = sqlite3.connect(path)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(SCHEMA)
        mode = "replay" if replay else "offline"
        with db:
            db.execute("INSERT OR IGNORE INTO settings VALUES ('mode', ?)", (mode,))
            if db.execute("SELECT value FROM settings WHERE key = 'mode'").fetchone()[0] != mode:
                raise ValueError("Replay and operational observations require separate databases")
        return db
    except BaseException:
        db.close()
        raise


def normalize(snapshot, *, replay):
    if snapshot["schema_version"] != 1:
        raise ValueError("Unsupported snapshot version")
    seen = timestamp(snapshot["observed_at"])
    policy = snapshot["source_policy"]
    status = policy["status"]
    if status not in POLICIES or (status == "fixture") != replay:
        raise ValueError("Source policy is incompatible with this database mode")
    permission = policy.get("permission_ref")
    if status == "approved":
        permission = label(permission)
    verified = status in {"approved", "fixture"} and boolean(policy.get("metrics_verified")) is True
    if not isinstance(snapshot["channels"], list) or not isinstance(snapshot["articles"], list):
        raise ValueError("Expected channel and article lists")
    channels = {}
    for row in snapshot["channels"]:
        slug = row["channel"]
        if not isinstance(slug, str) or not SLUG.fullmatch(slug) or slug in channels:
            raise ValueError("Invalid or repeated channel")
        channels[slug] = label(row["name"])
    if not channels:
        raise ValueError("Expected at least one observed channel")
    articles = {}
    source = label(snapshot["source"])
    for row in snapshot["articles"]:
        url = canonical(row["url"])
        slug = row["channel"]
        published = timestamp(row["published_at"])
        if slug not in channels or published > seen or url in articles:
            raise ValueError("Unknown channel, future publication or duplicate URL within snapshot")
        if "observed_at" in row and timestamp(row["observed_at"]) != seen:
            raise ValueError("Article and snapshot observation times must match")
        title = label(row["title"])
        ai = boolean(row["ai"]) if "ai" in row else bool(topic_basis(title))
        observation = (url, seen, title, ai, counter(row.get("views")), counter(row.get("comments")),
                       boolean(row.get("comments_open")), source, status, verified, permission)
        articles[url] = ((url, slug, published), observation)
    return seen, channels, articles


def dzen_snapshot(raw, slug, observed_at):
    """Adapt one saved export page. Its public counters remain unverified."""
    channel = raw["channel"]
    source = channel["source"]
    if (not SLUG.fullmatch(slug) or channel["status"] != "ok" or
            re.split(r"[?#]", source["feed_link"], 1)[0] != f"{ORIGIN}/{slug}" or
            not re.fullmatch(r"[a-f0-9]{24}", source["publisher_id"]) or
            not isinstance(raw["items"], list)):
        raise ValueError("Unexpected Dzen export or channel identity")
    articles = {}
    for card in raw["items"]:
        if card.get("item_type") != "native" or card.get("publisher_id") != source["publisher_id"]:
            continue
        try:
            url = canonical(card.get("link"))
        except ValueError:
            continue
        date, kind, _ = publication_date(card.get("publication_date"), None)
        if kind != "exact" or not card.get("title"):
            continue
        social = card.get("socialInfo")
        social = social if isinstance(social, dict) else {}
        comments_open = social.get("commentsEnabled")
        tags = [str(tag.get("title") or tag.get("name") or "").casefold()
                for tag in (card.get("interests") or []) if isinstance(tag, dict)]
        articles.setdefault(url, {
            "url": url, "channel": slug, "title": card["title"], "published_at": date,
            "ai": bool(topic_basis(card["title"], str(card.get("text") or "")[:300], tags)),
            "views": count(card.get("views")), "comments": count(social.get("commentCount")),
            "comments_open": comments_open if type(comments_open) is bool else None,
        })
    return {"schema_version": 1, "observed_at": observed_at, "source": "dzen_export",
            "source_policy": {"status": "unverified", "metrics_verified": False},
            "channels": [{"channel": slug, "name": source["title"]}], "articles": list(articles.values())}


def insert_checked(db, table, row, where, key):
    # Callers supply fixed table and column names; only values enter the database.
    placeholders = ", ".join("?" for _ in row)
    db.execute(f"INSERT OR IGNORE INTO {table} VALUES ({placeholders})", row)
    if tuple(db.execute(f"SELECT * FROM {table} WHERE {where}", key).fetchone()) != row:
        raise ValueError(f"Conflicting saved data in {table}: {key}")


def ingest(db, snapshot, *, replay=False):
    seen, channels, articles = normalize(snapshot, replay=replay)
    snapshot_urls = {slug: [] for slug in channels}
    with db:
        db.execute("BEGIN IMMEDIATE")
        db.executemany("INSERT OR IGNORE INTO channels VALUES (?, ?)", channels.items())
        for article, observation in articles.values():
            url, slug, _ = article
            insert_checked(db, "articles", article, "url = ?", (url,))
            insert_checked(db, "observations", observation, "url = ? AND seen = ?", (url, seen))
            snapshot_urls[slug].append(url)
        for slug, urls in snapshot_urls.items():
            insert_checked(db, "snapshots", (slug, seen, json.dumps(sorted(urls))),
                           "channel = ? AND seen = ?", (slug, seen))
    return {"channels": len(channels), "articles": len(articles), "observed_at": iso(seen)}


def age_cohort(history, band, *, verified=True):
    lower, upper = (edge * HOUR for edge in band)
    by_url = {}
    for row in history:
        age = row["seen"] - row["published"]
        if (lower <= age < upper and bool(row["verified"]) == verified
                and row["views"] is not None and row["comments"] is not None):
            by_url.setdefault(row["url"], row)
    # Use the first complete reading in the band, at most 10 of the newest articles.
    sample = sorted(by_url.values(), key=lambda row: (-row["published"], row["url"]))[:10]
    discussed = sum(row["comments"] > 0 for row in sample)
    return {
        "age_hours": list(band),
        "views_known": len(sample),
        "median_views": median([row["views"] for row in sample]) if sample else None,
        "discussion_rate": discussed / len(sample) if sample else None,
        "discussed": discussed,
    }


def channel_history(rows, latest, as_of):
    first_by_url = {}
    for row in rows:
        first_by_url.setdefault(row["url"], row["seen"])
    # Keep the current article out of the history even when an early item was seen before.
    mature = [row for row in rows if 24 * HOUR <= as_of - row["published"] < 14 * 24 * HOUR]
    cohorts = [age_cohort(mature, band) for band in BANDS]
    observed = [age_cohort(mature, band, verified=False) for band in BANDS]
    selected = next((cohort for cohort in cohorts if cohort["views_known"] >= MIN_SAMPLE), None)
    known_ai = {row["url"] for row in mature if row["verified"] and row["ai"] == 1}
    discussed_days = {datetime.fromtimestamp(row["published"], EDITORIAL_TIMEZONE).date() for row in mature
                      if row["verified"] and row["ai"] == 1 and (row["comments"] or 0) > 0}
    sample = selected or max(cohorts, key=lambda cohort: cohort["views_known"])
    strong = selected and selected["median_views"] >= MIN_MEDIAN and selected["discussed"] >= 2
    # Show mature, verified data as evidence even when individual AI articles are few.
    if not selected or len(known_ai) < 2 or len(discussed_days) < 2:
        status, confidence = "insufficient_evidence", "insufficient"
        reason = "Нужна сопоставимая история и обсуждения ИИ-статей в разные дни."
    elif strong:
        status, confidence = "confirmed_candidate", "observed"
        reason = "Достаточная медиана общего потока и повторяющиеся обсуждения ИИ-статей."
    else:
        status, confidence = "low_priority", "observed"
        reason = "Наблюдаемая история ниже порога просмотров или обсуждений."
    return {
        **sample, "verified": bool(selected), "status": status, "confidence": confidence,
        "reason": reason, "mature_ai_articles": len(known_ai), "ai_discussion_days": len(discussed_days),
        "unverified_age_cohorts": [cohort for cohort in observed if cohort["views_known"]],
        "ai_share": f"{sum(row['ai'] == 1 for row in latest)} / {len(latest)}" if latest and
                    all(row["ai"] is not None for row in latest) else None,
    }, first_by_url


def fresh_candidate(row, first_seen, as_of, history):
    return (history["status"] == "confirmed_candidate" and row["verified"] and row["ai"] == 1
            and row["comments_open"] == 1 and row["comments"] is not None and row["comments"] <= 3
            and 0 <= as_of - row["seen"] <= FRESHNESS
            and 0 <= first_seen - row["published"] <= WINDOW
            and 0 <= as_of - row["published"] <= WINDOW)


def decision_at(db, url, as_of):
    row = db.execute(
        "SELECT action FROM decisions WHERE url = ? AND recorded <= ? ORDER BY recorded DESC, id DESC LIMIT 1",
        (url, as_of),
    ).fetchone()
    return row["action"] if row and row["action"] != "undo" else None


def queue_snapshot(db, as_of, *, replay=False):
    decisions = {}
    channels, articles = [], []
    newest_snapshot = None
    with db:
        db.execute("BEGIN IMMEDIATE")
        for channel in db.execute("SELECT * FROM channels ORDER BY slug"):
            slug = channel["slug"]
            newest = db.execute("SELECT * FROM snapshots WHERE channel = ? AND seen <= ? ORDER BY seen DESC LIMIT 1",
                                (slug, as_of)).fetchone()
            if not newest:
                continue
            if newest_snapshot is None or newest["seen"] > newest_snapshot:
                newest_snapshot = newest["seen"]
            rows = db.execute(
                """SELECT o.*, a.published FROM observations o JOIN articles a USING(url)
                   WHERE a.channel = ? AND o.seen <= ? ORDER BY o.seen, o.url""", (slug, as_of)).fetchall()
            urls = set(json.loads(newest["urls"]))
            latest = [row for row in rows if row["seen"] == newest["seen"] and row["url"] in urls]
            history, first_seen = channel_history(rows, latest, as_of)
            channels.append({"slug": slug, "name": channel["name"], "url": f"{ORIGIN}/{slug}",
                             "status": history["status"], "history": history, "reason": history["reason"],
                             "ai_share": history["ai_share"], "guru_median": None,
                             "latest_observed_at": iso(newest["seen"]), "stale": as_of - newest["seen"] > FRESHNESS})
            for row in latest:
                url = row["url"]
                if not fresh_candidate(row, first_seen[url], as_of, history):
                    continue
                db.execute("""INSERT INTO offers VALUES (?, ?)
                              ON CONFLICT(url) DO UPDATE SET offered = MIN(offered, excluded.offered)""", (url, as_of))
                decision = decision_at(db, url, as_of)
                if decision:
                    decisions[url] = decision
                articles.append({
                    "url": url, "channel": slug, "title": row["title"], "ai": True,
                    "evidence": "verified", "comments_open": True, "comments": row["comments"], "views": row["views"],
                    "published_at": iso(row["published"]), "observed_at": iso(row["seen"]),
                    "first_seen_at": iso(first_seen[url]), "source": row["source"], "source_policy": row["policy"],
                    "offer_at": iso(db.execute("SELECT offered FROM offers WHERE url = ?", (url,)).fetchone()[0]),
                })
    articles.sort(key=lambda row: (-timestamp(row["published_at"]), row["comments"], row["url"]))
    return {"channels": channels, "articles": articles, "decisions": decisions, "demo": [],
            "latest_observed_at": iso(newest_snapshot), "as_of": iso(as_of), "replay": replay}


def mark(db, url, action, now):
    url = canonical(url)
    if action not in ACTIONS:
        raise ValueError("Invalid queue action")
    with db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM offers WHERE url = ? AND offered <= ?", (url, now)).fetchone():
            raise ValueError("Article has not been offered as of this time")
        previous = decision_at(db, url, now)
        if previous != (None if action == "undo" else action):
            db.execute("INSERT INTO decisions(url, action, recorded) VALUES (?, ?, ?)", (url, action, now))


def replay_sequence(db, steps):
    if db.execute("SELECT 1 FROM snapshots LIMIT 1").fetchone():
        raise ValueError("Run a replay sequence in a fresh replay database")
    results = []
    for step in steps:
        snapshot = step["snapshot"]
        when = timestamp(snapshot["observed_at"])
        ingest(db, snapshot, replay=True)
        queue = queue_snapshot(db, when, replay=True)
        results.append({
            "step": step["step"], "as_of": queue["as_of"],
            "pending": [row for row in queue["articles"] if row["url"] not in queue["decisions"]],
            "handled": queue["decisions"],
            "total_offers": db.execute("SELECT COUNT(*) FROM offers").fetchone()[0],
        })
        if "mark_after" in step:
            action = step["mark_after"]
            mark(db, action["url"], action["action"], when)
    return {"replay": True, "steps": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--replay", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    saved = commands.add_parser("import")
    saved.add_argument("file", type=Path)
    scout = commands.add_parser("import-signals")
    scout.add_argument("file", type=Path)
    dzen = commands.add_parser("import-dzen")
    dzen.add_argument("file", type=Path)
    dzen.add_argument("--channel", required=True)
    dzen.add_argument("--observed-at", required=True)
    sequence = commands.add_parser("replay-sequence")
    sequence.add_argument("file", type=Path)
    snapshot = commands.add_parser("snapshot")
    snapshot.add_argument("--as-of")
    decision = commands.add_parser("mark")
    decision.add_argument("url")
    decision.add_argument("action", choices=sorted(ACTIONS))
    decision.add_argument("--as-of")
    server = commands.add_parser("serve")
    server.add_argument("--port", type=int, default=8765)
    server.add_argument("--as-of")
    args = parser.parse_args()
    try:
        with closing(connect(args.db, replay=args.replay)) as db:
            if args.command == "replay-sequence":
                if not args.replay:
                    parser.error("replay-sequence requires --replay")
                result = replay_sequence(db, json.loads(args.file.read_bytes())["steps"])
            elif args.command == "import-signals":
                from dzen_first_car_signals import ingest_signals
                result = ingest_signals(db, json.loads(args.file.read_bytes()), replay=args.replay)
            elif args.command in {"import", "import-dzen"}:
                data = json.loads(args.file.read_bytes())
                if args.command == "import-dzen":
                    data = dzen_snapshot(data, args.channel, args.observed_at)
                result = ingest(db, data, replay=args.replay)
            else:
                if args.as_of and not args.replay:
                    parser.error("--as-of requires --replay")
                now = timestamp(args.as_of) if args.as_of else int(datetime.now(UTC).timestamp())
                if args.command == "serve":
                    from dzen_first_car_local import serve
                    serve(args.db, args.port, args.replay, now if args.as_of else None)
                    return
                if args.command == "mark":
                    mark(db, args.url, args.action, now)
                    result = {"url": args.url, "action": args.action}
                else:
                    from dzen_first_car_signals import signal_snapshot
                    result = queue_snapshot(db, now, replay=args.replay)
                    result["signals"] = signal_snapshot(db, now)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
