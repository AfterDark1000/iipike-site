"""First-response and sitemap diagnostic for issue #215."""

import argparse
import gzip
import hashlib
import io
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, getproxies

ORIGIN = "https://dzen.ru"
AGENT = "IIPikeDzenStageA"
TERMS_PATH = "/legal/ru/termsofuse/index.html"
REVIEWED_TERMS = "e02596e5379727da4825f8d32a3912a4c08939541ea912c085fc4ef6f3c71cd9"
INDEXES = {
    "articles": "/sitemaps/native_v2/sitemap.xml",
    "channels": "/sitemaps/channels_v2/sitemap.xml",
}
CHANNELS = ("/techinsider", "/aimira_tech", "/neural_network_it")
ARTICLE = re.compile(r"https://dzen\.ru/a/[A-Za-z0-9_-]{16}")
CHANNEL = re.compile(r"https://dzen\.ru/(?:id/[a-f0-9]{24}|[A-Za-z0-9_.-]+)")
LIMIT = 8_000_000
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
REDIRECTS = {301, 302, 303, 307, 308}
ACCESS_ERRORS = {401, 403, 429}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = build_opener(NoRedirect())


def timestamp():
    return datetime.now(UTC).isoformat(timespec="seconds")


def http_get(url):
    request = Request(url, headers={"User-Agent": f"{AGENT}/0.1"})
    try:
        with OPENER.open(request, timeout=20) as response:
            body = response.read(LIMIT + 1)
            if len(body) > LIMIT:
                raise ValueError("Response exceeds byte limit")
            return response.status, response.headers, body
    except HTTPError as error:
        with error:
            return error.code, error.headers, b""


def robots_rules(text):
    groups = []
    agents, rules = [], []
    for line in text.splitlines():
        key, _, value = line.split("#", 1)[0].partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        if key in {"allow", "disallow"} and agents and value:
            rules.append((key == "allow", value))
    groups.append((agents, rules))
    return groups


def allowed(groups, path, agent):
    if path.startswith("/search"):
        return False
    matches = [
        (len(name) if name != "*" else 0, rules)
        for names, rules in groups
        for name in names
        if name == "*" or name in agent.lower()
    ]
    if not matches:
        return False
    longest = max(length for length, _ in matches)
    decisions = []
    for length, rules in matches:
        if length != longest:
            continue
        for permit, pattern in rules:
            literal = pattern.removesuffix("$")
            regex = re.escape(literal).replace(r"\*", ".*")
            if re.match(regex + (r"\Z" if literal != pattern else ""), path):
                decisions.append((len(literal), permit))
    return max(decisions, default=(0, True))[1]


def observed_response(url, status, headers, size=None):
    result = {"url": url, "at_utc": timestamp(), "http_status": status}
    if size is not None:
        result["bytes"] = size
    location = headers.get("location")
    if location:
        target = urlsplit(urljoin(url, location))
        result["redirect_target"] = f"{target.scheme}://{target.hostname}{target.path}"
    return result


def checked_get(groups, path, observations):
    if not allowed(groups, path, AGENT):
        raise ValueError(f"robots.txt disallows {path}")
    time.sleep(2)
    url = ORIGIN + path
    status, headers, body = http_get(url)
    size = len(body) if status < 300 else None
    observations.append(observed_response(url, status, headers, size))
    return status, headers, body


def access_status(http_status):
    if http_status in REDIRECTS:
        return "redirect_not_followed"
    if http_status in ACCESS_ERRORS:
        return "blocked"
    return None


def sitemap(groups, kind, observations, today):
    status, _, body = checked_get(groups, INDEXES[kind], observations)
    if status != 200:
        return {"status": "unavailable"}, []
    shards = ET.fromstring(body).findall(f"{NS}sitemap/{NS}loc")
    folder = "native_v2/native" if kind == "articles" else "channels_v2/channels"
    shard_pattern = re.compile(rf"{re.escape(ORIGIN)}/sitemaps/{folder}-sitemap-[a-z0-9]+\.xml")
    valid = [item.text for item in shards if item.text and shard_pattern.fullmatch(item.text)]
    summary = {"index_entries": len(shards)}
    if not valid:
        return summary, []
    # One shard per index is enough to see which fields the service publishes.
    shard_url = (valid[-1] if kind == "articles" else valid[0]) + ".gz"
    status, _, body = checked_get(groups, urlsplit(shard_url).path, observations)
    summary["shard_url"] = shard_url
    if status != 200:
        return summary, []
    with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
        xml = compressed.read(LIMIT + 1)
    if len(xml) > LIMIT:
        raise ValueError("Uncompressed sitemap exceeds byte limit")
    entries = ET.fromstring(xml).findall(f"{NS}url")
    pattern = ARTICLE if kind == "articles" else CHANNEL
    urls = {}
    for entry in entries:
        url = entry.findtext(f"{NS}loc", "")
        if pattern.fullmatch(url) and allowed(groups, urlsplit(url).path, AGENT):
            urls[url] = entry.findtext(f"{NS}lastmod")
    recent = today - timedelta(days=29)
    summary.update(
        rows=len(entries),
        unique_matching_urls=len(urls),
        with_lastmod_in_30_days=sum(recent.isoformat() <= (day or "") <= today.isoformat()
                                    for day in urls.values()),
        fields=sorted({child.tag.removeprefix(NS) for entry in entries for child in entry}),
    )
    newest = sorted(urls.items(), key=lambda pair: (pair[1] or "", pair[0]), reverse=True)
    return summary, newest


def first_document_probe(groups, urls, executable):
    from playwright.sync_api import Error, sync_playwright

    proxy = getproxies().get("https")
    launch = {"executable_path": executable} if executable else {}
    if proxy:
        launch["proxy"] = {"server": proxy}
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch)
        version = browser.version
        for url in urls:
            with browser.new_context(java_script_enabled=False, service_workers="block",
                                     accept_downloads=False) as context:
                page = context.new_page()
                agent = page.evaluate("navigator.userAgent")
                result = {"url": url, "at_utc": timestamp(), "status": "robots_denied"}
                results.append(result)
                if not allowed(groups, urlsplit(url).path, agent):
                    continue

                def intercept(route):
                    request = route.request
                    if request.url != url or request.resource_type != "document":
                        route.abort()
                        return
                    try:
                        # Keep the first hop. Render only HTML returned by this allowed
                        # URL, with every subresource blocked and no session reused.
                        response = route.fetch(max_redirects=0, timeout=20_000)
                        length = response.headers.get("content-length")
                        result.update(observed_response(url, response.status, response.headers))
                        status = access_status(response.status)
                        if status:
                            result["status"] = status
                        elif response.ok and response.headers.get("content-type", "").startswith("text/html"):
                            if length and (not length.isdecimal() or int(length) > LIMIT):
                                result["status"] = "invalid_response"
                            else:
                                result["status"] = "found_but_not_checked"
                                route.fulfill(response=response)
                                return
                        else:
                            result["status"] = "unexpected_response"
                    except Error as error:
                        result.update(status="transport_error", reason=str(error).splitlines()[0])
                    route.abort()

                page.route("**/*", intercept)
                time.sleep(2)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                    inspect_document(page, url, result)
                except Error as error:
                    if result["status"] == "robots_denied":
                        result.update(status="transport_error", reason=str(error).splitlines()[0])
                if result.get("http_status") in ACCESS_ERRORS:
                    break
        browser.close()
    return {"mode": "first_document_only", "chromium_version": version, "pages": results}


def inspect_document(page, url, result):
    canonical = page.locator('link[rel="canonical"]').first
    article_type = page.locator('meta[property="og:type"][content="article"]')
    title = page.locator("h1").all_text_contents()
    result["document_title"] = page.title().strip() or None
    links = page.locator("a[href]").evaluate_all("(nodes) => nodes.map(n => n.href.split(/[?#]/, 1)[0])")
    result["direct_article_links_in_html"] = len({href for href in links if ARTICLE.fullmatch(href)})
    if (ARTICLE.fullmatch(url) and canonical.count() and canonical.get_attribute("href") == url
            and title and title[0].strip() and article_type.count()):
        result.update(status="direct_verified", title=title[0].strip())


def run(args):
    status, headers, robots = http_get(ORIGIN + "/robots.txt")
    if status != 200 or not headers.get("content-type", "").startswith("text/plain"):
        raise ValueError(f"robots.txt unavailable or unexpected (HTTP {status})")
    groups = robots_rules(robots.decode("utf-8-sig"))
    report = {"at_utc": timestamp(), "http": [observed_response(
        ORIGIN + "/robots.txt", status, headers, len(robots)
    )], "robots_sha256": hashlib.sha256(robots).hexdigest()}
    _, _, terms = checked_get(groups, TERMS_PATH, report["http"])
    report["terms_sha256"] = hashlib.sha256(terms).hexdigest()
    if report["terms_sha256"] != REVIEWED_TERMS:
        raise ValueError("Dzen terms differ from the reviewed revision")
    report["sitemaps"] = {}
    today = datetime.now(UTC).date()
    sample = []
    for kind in INDEXES:
        summary, rows = sitemap(groups, kind, report["http"], today)
        report["sitemaps"][kind] = summary
        if kind == "articles":
            sample = rows[:30]
        if report["http"][-1]["http_status"] in ACCESS_ERRORS:
            break
    controls = ("/articles", *CHANNELS)
    if sample:
        controls += (urlsplit(sample[0][0]).path,)
    for path in controls:
        if report["http"][-1]["http_status"] in ACCESS_ERRORS:
            break
        checked_get(groups, path, report["http"])
    attempted = {item["url"]: item for item in report["http"]}
    report["article_sample"] = [
        {
            "url": url,
            "sitemap_lastmod": lastmod,
            "published_at": None,
            "status": access_status(attempted.get(url, {}).get("http_status"))
            or "found_but_not_checked",
        }
        for url, lastmod in sample
    ]
    if args.browser and not any(item["http_status"] in ACCESS_ERRORS for item in report["http"]):
        report["browser"] = first_document_probe(
            groups, [ORIGIN + path for path in controls], args.chromium
        )
        browser_results = {item["url"]: item for item in report["browser"]["pages"]}
        for article in report["article_sample"]:
            page = browser_results.get(article["url"], {})
            if page.get("status") == "direct_verified":
                article.update(status="direct_verified", title=page["title"])
            elif page.get("status") in {"blocked", "redirect_not_followed"}:
                article["status"] = page["status"]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser", action="store_true",
        help="Inspect the first HTML document with Playwright, without JavaScript or redirects",
    )
    parser.add_argument("--chromium", help="Path to an existing Chromium installation")
    args = parser.parse_args()
    try:
        report = run(args)
    except (OSError, ValueError, URLError, ET.ParseError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
