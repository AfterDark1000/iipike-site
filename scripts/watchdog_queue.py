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
from scripts.site_publication_queue import _last_change, latest_site_first_publication, ready_items, git
from scripts.site_first_release_pr import exists_at, safe_git_blob_at

UTC = dt.timezone.utc

def snapshot(now=None):
    now = now or dt.datetime.now(UTC)
    git('fetch', 'origin', 'main', 'editorial-intake')
    rows = json.loads(safe_git_blob_at('origin/main', 'news.json'))
    last = latest_site_first_publication(rows, main_ref='origin/main')
    with contextlib.redirect_stdout(io.StringIO()) as capture:
        pending = ready_items('origin/editorial-intake', main_ref='origin/main')
    blocked = []
    for line in capture.getvalue().splitlines():
        if line.startswith('BLOCKED_UNVERIFIED_DZEN_REFERENCE: '):
            parts = line.split()
            if len(parts) >= 2:
                sid = parts[1]
                path = 'editorial_inbox/stories/' + sid + '.json'
                try:
                    if now - _last_change('origin/editorial-intake', path) > dt.timedelta(minutes=100):
                        blocked.append(sid)
                except (ValueError, OSError):
                    blocked.append(sid)
    overdue = []
    epoch = dt.datetime(1970, 1, 1, tzinfo=UTC)
    for item in pending:
        earliest = max(item['ready_at'], item['not_before'] or epoch,
                       last + dt.timedelta(hours=1) if last else epoch)
        delay = (now - earliest).total_seconds() / 60
        if delay > 100:
            overdue.append({'id': item['id'], 'minutes': round(delay)})
    newest = None
    for row in rows:
        sid = row.get('id', '')
        stamp = row.get('published_at_utc')
        if (isinstance(sid, str) and isinstance(stamp, str)
                and exists_at('origin/main', f'editorial_inbox/stories/{sid}.json')):
            try:
                time = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            except ValueError:
                continue
            if newest is None or time > newest[0]:
                newest = (time, sid)
    return {
        'overdue': overdue,
        'blocked_unverified_dzen_ids': blocked,
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
