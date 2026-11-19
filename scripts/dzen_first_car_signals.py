"""Local intake for direct Dzen links reported by an external source."""

from urllib.parse import urlsplit

from dzen_first_car import canonical, iso, label, timestamp

SIGNAL_WINDOW = 3600
SIGNAL_ACTIONS = {"checked", "commented"}


def ingest_signals(db, snapshot, *, replay=False):
    if snapshot["schema_version"] != 1 or not isinstance(snapshot["signals"], list):
        raise ValueError("Expected a version 1 signal snapshot")
    policy = snapshot["source_policy"]
    status = policy["status"]
    if status != ("fixture" if replay else "approved"):
        raise ValueError("Expected an approved source or a fixture in a replay database")
    permission_ref = label(policy["permission_ref"]) if status == "approved" else None
    stored = 0
    with db:
        db.execute("BEGIN IMMEDIATE")
        for signal in snapshot["signals"]:
            source = signal["source_url"]
            address = urlsplit(source)
            if (address.scheme != "https" or not address.hostname or address.username is not None
                    or "\\" in source or any(ch.isspace() for ch in source)):
                raise ValueError("Expected an HTTPS source URL without credentials")
            record = (canonical(signal["url"]), timestamp(signal["detected_at"]),
                      label(signal["title"]), source, status, permission_ref)
            stored += db.execute(
                """INSERT INTO scout_signals(url, detected, title, source_url, policy, permission_ref)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(url) DO UPDATE SET detected = excluded.detected, title = excluded.title,
                     source_url = excluded.source_url, policy = excluded.policy, permission_ref = excluded.permission_ref
                   WHERE excluded.detected < scout_signals.detected""", record).rowcount
    return {"signals_read": len(snapshot["signals"]), "signals_saved": stored}


def signal_snapshot(db, as_of):
    rows = db.execute(
        """SELECT s.* FROM scout_signals s
           WHERE s.detected BETWEEN ? AND ?
             AND NOT EXISTS (SELECT 1 FROM offers o WHERE o.url = s.url AND o.offered <= ?)
           ORDER BY s.detected DESC, s.url""", (as_of - SIGNAL_WINDOW, as_of, as_of))
    return [{
        "url": row["url"], "title": row["title"], "source_url": row["source_url"],
        "detected_at": iso(row["detected"]), "dzen_published_at": None, "dzen_comments": None,
        "verified": False,
        "action": row["action"] if row["marked"] is not None and row["marked"] <= as_of else None,
    } for row in rows]


def mark_signal(db, url, action, now):
    if action not in SIGNAL_ACTIONS:
        raise ValueError("Invalid signal action")
    with db:
        if not db.execute(
                """UPDATE scout_signals SET action = ?, marked = COALESCE(marked, ?)
                   WHERE url = ? AND detected BETWEEN ? AND ? AND (action IS NULL OR action = ?)
                     AND NOT EXISTS (SELECT 1 FROM offers WHERE offers.url = scout_signals.url AND offered <= ?)""",
                (action, now, canonical(url), now - SIGNAL_WINDOW, now, action, now)).rowcount:
            raise ValueError("Signal is unavailable or already marked")
