"""Rank Dzen channel candidates from saved public profiles and editorial evidence."""

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from dzen_stage_a3_probe import count
from dzen_stage_a5_audit import AI_TITLE, FLIGHT, SLUG, catalog_rows

GURU = "https://dzen.guru"
MEDIAN = re.compile(
    r"медиана охвата одной публикации около\s+([0-9][0-9 \u00a0\u202f]*)\s*просмотр",
    re.IGNORECASE,
)
RANGE = re.compile(r"разброс от\s+([0-9][0-9 \u00a0\u202f]*)\s+до\s+([0-9][0-9 \u00a0\u202f]*)")
TOPIC_EVIDENCE = {"dzen_publications", "publisher_site", "author_feed"}
MIN_MONTHLY_PUBLICATIONS = 4
PRIORITY_MEDIAN = 300
RESERVE_MEDIAN = 100


class ProfilePage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.visible = []
        self.channel_links = []
        self.hidden = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden = True
        if tag == "a":
            value = urlsplit(dict(attrs).get("href") or "")
            if value.scheme == "https" and value.netloc == "dzen.ru" and SLUG.fullmatch(value.path.lstrip("/")):
                if value.path not in {"/news", "/articles", "/video", "/shorts"}:
                    self.channel_links.append("https://dzen.ru" + value.path)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = False

    def handle_data(self, text):
        if not self.hidden and text.strip():
            self.visible.append(text.strip())


def public_profile(html, slug, observed_at):
    page = ProfilePage()
    page.feed(html)
    faq = next((line for line in page.visible if MEDIAN.search(line)), "")
    median_label = MEDIAN.search(faq)
    range_label = RANGE.search(faq)
    record = {}
    decoder = json.JSONDecoder()
    prefix = '{"slug":' + json.dumps(slug)
    for script in FLIGHT.finditer(html):
        if "publications30days" not in script[1]:
            continue
        packet = json.loads(script[1])
        if isinstance(packet, list) and len(packet) == 2 and isinstance(packet[1], str):
            offset = packet[1].find(prefix)
            if offset >= 0:
                record, _ = decoder.raw_decode(packet[1][offset:])
                break
    if not record or not page.channel_links:
        raise ValueError(f"Missing public channel identity or metadata: {slug}")
    expected = f"https://dzen.ru/{slug}"
    channel_url = expected if expected in page.channel_links else page.channel_links[0]
    if channel_url != expected and not channel_url.startswith("https://dzen.ru/id/"):
        raise ValueError(f"Public profile links to a different channel: {slug}")
    faq_views = int("".join(median_label[1].split())) if median_label else None
    posts = count(record.get("publications30days"))
    total_views = count(record.get("views30days"))
    possible_mean = (range_label is None and faq_views is not None and posts
                     and total_views is not None and abs(faq_views * posts - total_views) <= posts / 2)
    return {
        "channel": slug,
        "name": record["title"].strip(),
        "url": channel_url,
        "metric_source": f"{GURU}/channels/{slug}",
        "observed_at": observed_at,
        "profile_updated_at": record.get("updatedAt"),
        "niches": [t["title"] for t in (record.get("topics") or []) if isinstance(t, dict) and t.get("title")],
        "subscribers": count(record.get("subscribers")),
        "publications_30d": posts,
        "median_views": None if possible_mean else faq_views,
        "guru_faq_views": faq_views,
        "guru_views_30d_for_metric_check": total_views if possible_mean else None,
        "metric_quality": ("possible_mean_fallback" if possible_mean else
                           "guru_faq_median" if faq_views is not None else "missing_median"),
        "median_observed_range": [int("".join(n.split())) for n in range_label.groups()] if range_label else None,
        "median_sample_size": None,
        "median_post_age": None,
    }


def rank_profiles(profiles, topic_evidence, catalog_urls):
    shortlist, held = [], []
    for profile in profiles:
        slug = profile["channel"]
        evidence = topic_evidence.get(slug) or {}
        links = set(evidence.get("urls") or [])
        topical = (evidence.get("kind") in TOPIC_EVIDENCE and len(links) >= 2
                   and all(urlsplit(link).scheme == "https" and urlsplit(link).netloc for link in links))
        typical = profile["median_views"]
        if typical is None:
            status = "unverified_median"
        elif typical < RESERVE_MEDIAN:
            status = "below_pilot_median"
        elif (profile["publications_30d"] or 0) < MIN_MONTHLY_PUBLICATIONS:
            status = "insufficient_publication_frequency"
        elif not topical:
            status = "unverified_recurring_ai"
        else:
            status = "priority" if typical >= PRIORITY_MEDIAN else "reserve"
        row = {
            **profile,
            "catalog_sources": catalog_urls.get(slug, []),
            "topic_evidence": evidence or None,
            "ai_share_on_dzen": evidence.get("ai_share_on_dzen"),
            "historical_discussions_on_dzen": evidence.get("historical_discussions_on_dzen"),
            "audience_status": "unverified",
            "status": status,
        }
        (shortlist if status in {"priority", "reserve"} else held).append(row)

    shortlist.sort(key=lambda row: (
        row["status"] != "priority",
        row["topic_evidence"]["kind"] != "dzen_publications",
        -row["median_views"],
        row["channel"],
    ))
    held.sort(key=lambda row: (row["status"], -(row["median_views"] or 0), row["channel"]))
    return shortlist[:20], held


def profile_plan(rows):
    candidates = [row for row in rows if SLUG.fullmatch(row["slug"])
                  and (count(row.get("publications30days")) or 0) >= MIN_MONTHLY_PUBLICATIONS]
    candidates.sort(key=lambda row: (
        row.get("views30daysEstimated") is not False,
        -(count(row.get("viewsObservedDays")) or 0),
        row["slug"],
    ))
    topical, broad = [], []
    for row in candidates:
        text = row["title"] + " " + (row.get("description") or "")[:500]
        (topical if AI_TITLE.search(text) else broad).append(row["slug"])
    chosen = topical[:3] + broad[:3] + broad[3:] + topical[3:]
    return [f"{GURU}/channels/{slug.removeprefix('id/')}" for slug in chosen[:6]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", nargs=2, metavar=("URL", "HTML"), action="append", required=True)
    parser.add_argument("--profiles", type=Path)
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--topic-evidence", type=Path)
    args = parser.parse_args()
    if args.profiles is None and (args.receipts or args.topic_evidence):
        parser.error("Pass --profiles with --receipts and --topic-evidence")
    if args.profiles is not None and (args.receipts is None or args.topic_evidence is None):
        parser.error("Pass --receipts and --topic-evidence with --profiles")
    catalog_urls, catalog_inputs = {}, []
    try:
        for url, file in args.catalog:
            rows = catalog_rows(Path(file).read_text(encoding="utf-8"))
            catalog_inputs.append({"url": url, "rows": len(rows), "profile_plan": profile_plan(rows)})
            for row in rows:
                catalog_urls.setdefault(row["slug"], []).append(url)
        profiles = []
        evidence = {}
        if args.profiles is not None:
            for receipt in json.loads(args.receipts.read_bytes()):
                slug = receipt["channel"]
                if receipt["http_status"] != 200 or not SLUG.fullmatch(slug):
                    continue
                html = (args.profiles / f"{slug.replace('/', '_')}.profile").read_text(encoding="utf-8")
                profiles.append(public_profile(html, slug, receipt["observed_at"]))
            evidence = json.loads(args.topic_evidence.read_bytes())
            if "shortlist" in evidence and "held" in evidence:
                evidence = {row["channel"]: row["topic_evidence"] for row in evidence["shortlist"] + evidence["held"]
                            if row["topic_evidence"]}
        shortlist, held = rank_profiles(profiles, evidence, catalog_urls)
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps({
        "catalog_inputs": catalog_inputs,
        "unique_catalog_channels": len(catalog_urls),
        "profiles_reviewed": len(profiles),
        "rules": {
            "priority_median": PRIORITY_MEDIAN,
            "reserve_median": RESERVE_MEDIAN,
            "minimum_publications_30d": MIN_MONTHLY_PUBLICATIONS,
            "regular_use_internal_export": "permission_not_established",
        },
        "shortlist": shortlist,
        "held": held,
    }, indent=2))


if __name__ == "__main__":
    main()
