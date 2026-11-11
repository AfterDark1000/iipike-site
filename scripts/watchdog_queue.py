#!/usr/bin/env python3
"""Read-only local Git health snapshot of site-first queue. Does not publish."""
import argparse
import contextlib
import datetime as dt
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.site_publication_queue import _last_change, latest_site_first_publication, ready_items, git, SITE_TZ
from scripts.site_first_release_pr import exists_at, safe_git_blob_at
from scripts.render_site_publication_queue import forecast_order

UTC = dt.timezone.utc


def active_publication_minutes(begin, end):
    """Count elapsed daytime release minutes; exclude 01:00–07:00 locally.

    Overnight holding time cannot make a story overdue. An already-overdue
    article keeps its accumulated daytime minutes until publication.
    """
    if begin.tzinfo is None or end.tzinfo is None:
        raise ValueError("Queue watchdog timestamps require timezone offsets")
    if end <= begin:
        return (end - begin).total_seconds() / 60
    elapsed = (end - begin).total_seconds() / 60
    day = begin.astimezone(SITE_TZ).date()
    final_day = end.astimezone(SITE_TZ).date()
    while day <= final_day:
        quiet_start = dt.datetime.combine(day, dt.time(1), SITE_TZ).astimezone(UTC)
        quiet_end = dt.datetime.combine(day, dt.time(7), SITE_TZ).astimezone(UTC)
        overlap = (min(end, quiet_end) - max(begin, quiet_start)).total_seconds() / 60
        if overlap > 0:
            elapsed -= overlap
        day += dt.timedelta(days=1)
    return max(0, elapsed)



def overdue_publications(pending, last, now, *, threshold_minutes=100):
    """Compare with the REAL sequential hourly queue, not one shared due time.

    The dashboard may slide its *forecast* forward on each inspection; a
    watchdog deadline must instead be anchored at the last published issue
    and at the oldest available approved story/cover. Uses exactly the same
    selection order, cron minutes, quiet hours and spacing as the dashboard.
    A later article cannot become overdue before its own theoretical turn.
    """
    if not pending:
        return []
    if now.tzinfo is None:
        raise ValueError("Watchdog check needs a timezone-aware clock")
    anchor = min(item["ready_at"] for item in pending)
    rows = [{"id": item["id"], "ready_at": item["ready_at"],
             "publish_at": item.get("not_before"), "eligible": True}
            for item in pending]
    planned = forecast_order(rows, last, now=anchor)
    overdue = []
    for row, slot in planned:
        delay = active_publication_minutes(slot, now)
        if delay > threshold_minutes:
            overdue.append({"id": row["id"], "minutes": round(delay)})
    return overdue


def snapshot(now=None):
    now = now or dt.datetime.now(UTC)
    git('fetch', 'origin', 'main', 'editorial-intake')
    rows = json.loads(safe_git_blob_at('origin/main', 'news.json'))
    last = latest_site_first_publication(rows, main_ref='origin/main')
    with contextlib.redirect_stdout(io.StringIO()) as capture:
        pending = ready_items('origin/editorial-intake', main_ref='origin/main')
    blocked = []
    invalid_markdown = []
    for line in capture.getvalue().splitlines():
        if (line.startswith('BLOCKED_UNVERIFIED_DZEN_REFERENCE: ') or
                line.startswith('BLOCKED_INVALID_MARKDOWN: ')):
            parts = line.split()
            if len(parts) >= 2:
                sid = parts[1]
                path = 'editorial_inbox/stories/' + sid + '.json'
                try:
                    if now - _last_change('origin/editorial-intake', path) > dt.timedelta(minutes=100):
                        (invalid_markdown if line.startswith('BLOCKED_INVALID_MARKDOWN: ') else blocked).append(sid)
                except (ValueError, OSError):
                    (invalid_markdown if line.startswith('BLOCKED_INVALID_MARKDOWN: ') else blocked).append(sid)
    overdue = overdue_publications(pending, last, now)
    newest = None
    site_first_published = []
    for row in rows:
        sid = row.get('id', '')
        stamp = row.get('published_at_utc')
        if (isinstance(sid, str) and isinstance(stamp, str)
                and exists_at('origin/main', f'editorial_inbox/stories/{sid}.json')
                and exists_at('origin/main', f'articles/{sid}/index.html')):
            try:
                time = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            except ValueError:
                continue
            site_first_published.append({'id': sid, 'published_at_utc': time.isoformat()})
            if newest is None or time > newest[0]:
                newest = (time, sid)
    return {
        'overdue': overdue,
        'blocked_unverified_dzen_ids': blocked,
        'blocked_invalid_markdown_ids': invalid_markdown,
        'published_site_first': site_first_published,
        'newest_id': newest[1] if newest else None,
        'newest_published_at_utc': newest[0].isoformat() if newest else None,
        'last_published_at_utc': last.isoformat() if last else None,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        result = snapshot()
    except Exception as exc:
        result = {'check_error': type(exc).__name__ + ': ' + str(exc)[:180]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False), encoding='utf8')
    print('QUEUE_WATCHDOG:', json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    main()
