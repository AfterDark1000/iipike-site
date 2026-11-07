#!/usr/bin/env python3
"""Read-only Yandex analytics -> private GitHub repo. Never publish visitor data.

Requires secrets YANDEX_METRIKA_TOKEN, YANDEX_WEBMASTER_TOKEN and
HPII_PRIVATE_STATS_TOKEN, plus a pre-created PRIVATE repository named
AfterDark1000/iipike-analytics. No Yandex write endpoints are used.
"""
import base64
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

SITE = "iipike.ru"
PRIVATE_REPO = "AfterDark1000/iipike-analytics"
TZ = ZoneInfo("Asia/Yekaterinburg")
METRIKA_API = "https://api-metrika.yandex.net"
WEBMASTER_API = "https://api.webmaster.yandex.net"
GITHUB_API = "https://api.github.com"
USER_AGENT = "HPII-Yandex-Analytics/1.0 (aggregate read-only)"


class AnalyticsError(RuntimeError):
    pass


def request_json(base, path, token, params=None, *, method="GET", body=None):
    """Only send tokens to pinned first-party API hosts; never print token/body."""
    if base not in (METRIKA_API, WEBMASTER_API, GITHUB_API):
        raise AnalyticsError("Unexpected API host")
    if not token or "\n" in token or "\r" in token:
        raise AnalyticsError("Missing or invalid API credentials")
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json" if base == GITHUB_API else "application/json",
        "Authorization": ("Bearer " if base == GITHUB_API else "OAuth ") + token,
    }
    raw = None
    if body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=raw, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            response = resp.read(2_000_000)
            return json.loads(response.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Deliberately don't echo the response body or authorization headers.
        raise AnalyticsError(f"{base} returned HTTP {exc.code} for {path}") from None
    except urllib.error.URLError:
        raise AnalyticsError(f"{base} connection failed") from None
    except (ValueError, UnicodeError, json.JSONDecodeError):
        raise AnalyticsError(f"{base} sent invalid JSON") from None


def canonical_host(value):
    if not isinstance(value, str) or not value:
        return ""
    parsed = urllib.parse.urlsplit(value if "://" in value else "https://" + value)
    return (parsed.hostname or "").lower().rstrip(".")


def pick_metrika_counter(data, expected_id=None):
    candidates = []
    for row in data.get("counters", []):
        site2 = row.get("site2") or {}
        names = [site2.get("site"), row.get("site")]
        names += [m.get("site") for m in (row.get("mirrors2") or []) if isinstance(m, dict)]
        if SITE in {canonical_host(name) for name in names} and row.get("status") != "Deleted":
            candidates.append(row)
    if expected_id:
        candidates = [row for row in candidates if str(row.get("id")) == expected_id]
    if len(candidates) != 1:
        raise AnalyticsError("Metrica: expected exactly one accessible counter for iipike.ru; configure YANDEX_METRIKA_COUNTER_ID if needed")
    return str(candidates[0]["id"])


def parse_metrika_report(report, count, *, has_dimensions=False):
    if not isinstance(report, dict) or not isinstance(report.get("totals"), list):
        raise AnalyticsError("Metrica: report missing totals")
    result = {"sampled": bool(report.get("sampled", False))}
    if has_dimensions:
        rows = []
        for item in report.get("data", [])[:count]:
            dim = (item.get("dimensions") or [{}])[0]
            key = dim.get("name") if isinstance(dim, dict) else str(dim)
            rows.append({"value": key, "metrics": item.get("metrics", [])})
        result["rows"] = rows
        result["truncated"] = report.get("total_rows", len(rows)) > count
    else:
        result["totals"] = report["totals"]
    return result


def metrika_stats(token, date30, date7, yesterday, expected_id=None):
    counters = request_json(METRIKA_API, "/management/v1/counters", token,
                            {"search_string": SITE, "per_page": 1000})
    counter = pick_metrika_counter(counters, expected_id=expected_id)

    def report(start, metrics, *, dimensions=None, limit=100):
        params = {
            "id": counter, "date1": start, "date2": yesterday,
            "metrics": metrics, "accuracy": "full", "lang": "ru", "limit": limit,
        }
        if dimensions:
            params["dimensions"] = dimensions
            params["sort"] = "-" + metrics.split(",")[0]
        return request_json(METRIKA_API, "/stat/v1/data", token, params)

    metrics = "ym:s:visits,ym:s:users,ym:s:pageviews"
    return {
        "status": "ok", "counter_id": counter,
        "last_7_days": parse_metrika_report(report(date7, metrics), 0),
        "last_30_days": parse_metrika_report(report(date30, metrics), 0),
        "visits_by_day": parse_metrika_report(
            report(date30, metrics, dimensions="ym:s:date", limit=40), 40, has_dimensions=True),
        "traffic_sources": parse_metrika_report(
            report(date30, "ym:s:visits", dimensions="ym:s:trafficSource", limit=25),
            25, has_dimensions=True),
        "top_entry_pages": parse_metrika_report(
            report(date30, "ym:s:visits", dimensions="ym:s:startURLPath", limit=30),
            30, has_dimensions=True),
        "top_viewed_pages": parse_metrika_report(
            report(date30, "ym:pv:pageviews", dimensions="ym:pv:URLPath", limit=30),
            30, has_dimensions=True),
    }


def choose_webmaster_host(data):
    hosts = []
    for row in data.get("hosts", []):
        hostname = canonical_host(row.get("ascii_host_url"))
        if hostname == SITE and row.get("verified") is True:
            hosts.append(row)
    if not hosts:
        raise AnalyticsError("Webmaster: iipike.ru is not present as a VERIFIED site for this account")
    hosts.sort(key=lambda x: not str(x.get("ascii_host_url", "")).startswith("https://"))
    return hosts[0]["host_id"]


def webmaster_stats(token, start, yesterday):
    user = request_json(WEBMASTER_API, "/v4/user", token)
    uid = user.get("user_id")
    if not isinstance(uid, int):
        raise AnalyticsError("Webmaster: missing user_id")
    hosts = request_json(WEBMASTER_API, f"/v4/user/{uid}/hosts", token)
    host_id = choose_webmaster_host(hosts)
    root = f"/v4/user/{uid}/hosts/{urllib.parse.quote(host_id, safe='')}"
    start_at = start + "T00:00:00+05:00"
    end_at = yesterday + "T23:59:59+05:00"
    interval = {"date_from": start_at, "date_to": end_at}
    query_params = list(interval.items()) + [
        ("query_indicator", "TOTAL_SHOWS"),
        ("query_indicator", "TOTAL_CLICKS"),
        ("query_indicator", "AVG_SHOW_POSITION"),
    ]
    search = request_json(WEBMASTER_API, root + "/search-queries/all/history",
                          token, query_params)
    indexed = request_json(WEBMASTER_API, root + "/search-urls/in-search/history",
                           token, interval)
    indicators = search.get("indicators")
    if not isinstance(indicators, dict) or not isinstance(indexed.get("history"), list):
        raise AnalyticsError("Webmaster: unexpected history schema")
    return {
        "status": "ok", "host_id": host_id,
        "search_query_history": {
            key: indicators.get(key, []) for key in ("TOTAL_SHOWS", "TOTAL_CLICKS", "AVG_SHOW_POSITION")
        },
        "pages_in_search_history": indexed["history"],
    }


def date_window(now):
    local_today = now.astimezone(TZ).date()
    end = local_today - dt.timedelta(days=1)
    return ((end - dt.timedelta(days=29)).isoformat(),
            (end - dt.timedelta(days=6)).isoformat(), end.isoformat())


def collect(now, metrika_token, webmaster_token, *, counter_id=None):
    date30, date7, yesterday = date_window(now)
    report = {
        "schema_version": 1, "site": SITE,
        "generated_at_utc": now.astimezone(dt.timezone.utc).isoformat(),
        "timezone": "Asia/Yekaterinburg",
        "through_complete_day": yesterday,
        "last_30_days_from": date30, "last_7_days_from": date7,
        "metrika": {"status": "missing_credentials"},
        "webmaster": {"status": "missing_credentials"},
    }
    # Fail closed on connection/API errors: never silently write missing data as zero.
    for field, token, callback in (
        ("metrika", metrika_token, lambda: metrika_stats(token, date30, date7, yesterday, counter_id)),
        ("webmaster", webmaster_token, lambda: webmaster_stats(token, date30, yesterday)),
    ):
        if token:
            try:
                report[field] = callback()
            except AnalyticsError as exc:
                report[field] = {"status": "error", "reason": str(exc)}
    return report


def ensure_private_repo(token):
    data = request_json(GITHUB_API, "/repos/" + PRIVATE_REPO, token)
    if data.get("full_name") != PRIVATE_REPO or data.get("private") is not True:
        raise AnalyticsError("Statistics destination is not the expected private repository")
    if data.get("archived"):
        raise AnalyticsError("Private statistics destination is archived")


def save_private_json(token, path, payload):
    if not re.fullmatch(r"reports/(?:latest|[0-9]{4}-[0-9]{2}-[0-9]{2})\.json", path):
        raise AnalyticsError("Unexpected statistics path")
    urlpath = f"/repos/{PRIVATE_REPO}/contents/{path}"
    encoded = base64.b64encode((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()).decode()
    for attempt in range(3):
        try:
            existing = request_json(GITHUB_API, urlpath, token)
            sha = existing.get("sha")
        except AnalyticsError as exc:
            if "HTTP 404" not in str(exc):
                raise
            sha = None
        message = "chore: update private Yandex analytics snapshot [skip ci]"
        body = {"message": message, "content": encoded, "branch": "main"}
        if sha:
            body["sha"] = sha
        try:
            request_json(GITHUB_API, urlpath, token, method="PUT", body=body)
            return
        except AnalyticsError as exc:
            if "HTTP 409" not in str(exc) or attempt == 2:
                raise
            time.sleep(1)


def main():
    private_token = os.getenv("HPII_PRIVATE_STATS_TOKEN", "")
    metrika_token = os.getenv("YANDEX_METRIKA_TOKEN", "")
    webmaster_token = os.getenv("YANDEX_WEBMASTER_TOKEN", "")
    if not private_token or not (metrika_token or webmaster_token):
        print("NOT_CONFIGURED: configure HPII_PRIVATE_STATS_TOKEN and at least one Yandex read token in GitHub Secrets.")
        return 0
    now = dt.datetime.now(dt.timezone.utc)
    # Check privacy *before* collecting anything or writing a single file.
    ensure_private_repo(private_token)
    snapshot = collect(now, metrika_token, webmaster_token,
                       counter_id=os.getenv("YANDEX_METRIKA_COUNTER_ID") or None)
    if not any(snapshot[x]["status"] == "ok" for x in ("metrika", "webmaster")):
        raise AnalyticsError("Neither Yandex API returned valid data; no snapshot written")
    day = snapshot["through_complete_day"]
    save_private_json(private_token, f"reports/{day}.json", snapshot)
    save_private_json(private_token, "reports/latest.json", snapshot)
    print("PRIVATE_YANDEX_STATS_UPDATED:", day,
          "metrika:", snapshot["metrika"]["status"],
          "webmaster:", snapshot["webmaster"]["status"],
          "(no statistics stored in public repo)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AnalyticsError as exc:
        print("ANALYTICS_CHECK_FAILED:", exc, file=sys.stderr)
        sys.exit(1)
