"""Local A.2 diagnostic for three public Dzen articles."""

import argparse
import hashlib
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
import webbrowser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from http.client import HTTPException
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit
from urllib.request import getproxies

from playwright.sync_api import Error, sync_playwright

from dzen_stage_a_probe import (
    ACCESS_ERRORS, AGENT, ARTICLE, LIMIT, ORIGIN, REDIRECTS, REVIEWED_TERMS,
    TERMS_PATH, allowed, http_get, robots_rules, timestamp,
)

CONTROLS = (
    ("TechInsider", "large", ORIGIN + "/a/avc76LTmP0dR14pK"),
    ("Hi, AI", "independent_middle", ORIGIN + "/a/afRY8FgRSTPZefQ7"),
    ("Евгения Грунис", "small", ORIGIN + "/a/aO9TS4LAkjimNKgQ"),
)
ORIGIN_HOST = urlsplit(ORIGIN).hostname
ASSET_HOSTS = {"static.dzeninfra.ru", "avatars.dzeninfra.ru"}
SSO_HOSTS = {"sso.passport.yandex.ru", "login.vk.com", "id.vk.com"}
REVIEWED_HOSTS = {ORIGIN_HOST} | ASSET_HOSTS | SSO_HOSTS
PROTECTED_PATH = re.compile(r"^/(?:auth(?:orization)?|login|logout|oauth2?|passport|captcha)(?:[/.]|$)", re.I)
PROTECTED_QUERY = re.compile(r"^(?:.*token|access_code|auth|password|retpath|sso_.*|is_autologin.*)$", re.I)
FIELDS = (
    "final_url", "title", "channel", "published_at", "published_label", "views",
    "subscribers", "comments_visible", "comment_count",
)
MANUAL_STATUSES = {
    "Не проверял": "not_observed",
    "Статья открылась": "article_opened",
    "Запрошен вход или проверка": "access_prompt",
    "Статья не открылась": "article_unavailable",
}
REPORT_NAME = "dzen-a2-report.json"
DIAGNOSTIC_VERSION = 2
PAGE_SECONDS = 25
REQUEST_LIMIT = 80
MAX_REDIRECTS = 3


def request_parts(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443) or parsed.fragment):
            return None
    except ValueError:
        return None
    path = unquote(parsed.path or "/")
    if ("\\" in path or "%" in path or "//" in path
            or any(part in {".", ".."} for part in path.split("/"))
            or any(char in path for char in "?#")
            or any(ord(char) < 32 or ord(char) == 127 for char in path)):
        return None
    return parsed.hostname, path, parsed.query


def article_address(url):
    parts = request_parts(url)
    if not parts:
        return None
    host, path, _ = parts
    address = f"https://{host}{path}"
    return address if ARTICLE.fullmatch(address) else None


def approved_host(url):
    parts = request_parts(url)
    return parts[0] if parts and parts[0] in REVIEWED_HOSTS else None


def transport_error(exc):
    reason = getattr(exc, "reason", exc)
    code = getattr(reason, "winerror", None) or getattr(reason, "errno", None)
    if "Tunnel connection failed:" in str(reason):
        return "proxy_connect_failed"
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "certificate_verification_failed"
    if isinstance(reason, ssl.SSLError):
        return "tls_error"
    if isinstance(reason, socket.gaierror) or code in {11001, 11002, 11003, 11004}:
        return "dns_error"
    if isinstance(reason, TimeoutError) or code == 10060:
        return "timeout"
    if isinstance(reason, ConnectionError) or code in {10051, 10053, 10054, 10061, 10065}:
        return "connection_error"
    if isinstance(reason, ValueError):
        return "invalid_response"
    return "transport_error"


def windows_policy_request(url):
    """Try the system TLS client only when Python had no proxy for this URL."""
    if sys.platform != "win32":
        return None, "windows_client_unavailable"
    proxies = getproxies()
    if proxies.get("https") or proxies.get("all"):
        return None, "configured_proxy"
    curl = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "curl.exe"
    if not curl.is_file():
        return None, "windows_client_unavailable"
    try:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "policy"
            # -q disables local curl configuration. No redirects, proxy changes or TLS overrides.
            result = subprocess.run(
                [str(curl), "-q", "--silent", "--proto", "=https", "--no-location",
                 "--connect-timeout", "6", "--max-time", "15",
                 "--max-filesize", str(LIMIT), "--user-agent", f"{AGENT}/0.1",
                 "--output", str(output), "--write-out", "%{http_code}\n%{content_type}", "--", url],
                capture_output=True, encoding="utf-8", errors="replace", timeout=18,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            status, _, content_type = result.stdout.partition("\n")
            if not re.fullmatch(r"[1-5][0-9]{2}", status):
                errors = {6: "dns_error", 7: "connection_error", 28: "timeout",
                          35: "tls_error", 60: "certificate_verification_failed"}
                return None, errors.get(result.returncode, "transport_error")
            if result.returncode:
                # A response status was seen. Never use a partial policy document.
                return (int(status), {}, b""), "incomplete_response"
            with output.open("rb") as file:
                body = file.read(LIMIT + 1)
            if len(body) > LIMIT:
                return (int(status), {}, b""), "invalid_response"
            return (int(status), {"content-type": content_type.strip()}, body), None
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except OSError:
        return None, "transport_error"


class SiteRules:
    """Check the current rules of each reviewed host before requesting its content."""

    def __init__(self, get=http_get, fallback=windows_policy_request):
        self.get = get
        self.fallback = fallback
        self.rules = {}
        self.audit = {}
        self.fetches = {}

    def fetch(self, url, key):
        attempts = self.fetches[key] = []
        try:
            response = self.get(url)
        except (OSError, ValueError, HTTPException) as exc:
            reason = transport_error(exc)
            attempts.append({"client": "python", "http_status": None, "error": reason})
            if reason not in {
                "certificate_verification_failed", "tls_error", "dns_error", "timeout", "connection_error",
            }:
                return None
            response, reason = self.fallback(url)
            attempts.append({"client": "windows_curl", "http_status": response[0] if response else None,
                             "error": reason})
            return response
        attempts.append({"client": "python", "http_status": response[0], "error": None})
        return response

    def load(self, host):
        if host not in self.rules:
            self.rules[host] = None
            self.audit[host] = None
            response = self.fetch(f"https://{host}/robots.txt", host)
            if response:
                status, headers, body = response
                self.audit[host] = status
                attempt = self.fetches[host][-1]
                if attempt["error"]:
                    return None
                if host in ASSET_HOSTS and status in {404, 410}:
                    self.rules[host] = [(["*"], [])]
                elif status == 200:
                    if not headers.get("content-type", "").lower().startswith("text/plain"):
                        attempt["error"] = "unexpected_content_type"
                        return None
                    try:
                        rules = robots_rules(body.decode("utf-8-sig"))
                    except UnicodeDecodeError:
                        attempt["error"] = "invalid_encoding"
                        return None
                    if any(agents for agents, _ in rules):
                        self.rules[host] = rules
                    else:
                        attempt["error"] = "missing_user_agent_rules"
        return self.rules[host]

    def decision(self, url, browser_agent):
        parts = request_parts(url)
        if not parts:
            return "invalid_url"
        host, path, query = parts
        if host not in REVIEWED_HOSTS:
            return "host_outside_probe"
        rules = self.load(host)
        if rules is None:
            return "robots_unavailable"
        paths = {path, urlsplit(url).path or "/"}
        suffix = "?" + query if query else ""
        if not all(allowed(rules, value + suffix, agent)
                   for value in paths for agent in (AGENT, browser_agent)):
            return "robots_denied"
        if host in SSO_HOSTS or PROTECTED_PATH.match(path):
            return "authentication_or_challenge_path"
        if any(PROTECTED_QUERY.fullmatch(key) for key, _ in parse_qsl(query, keep_blank_values=True)):
            return "authentication_parameter"
        return None

    def check_terms(self):
        url = ORIGIN + TERMS_PATH
        denial = self.decision(url, AGENT)
        if denial:
            return denial
        response = self.fetch(url, "terms")
        if response is None or self.fetches["terms"][-1]["error"]:
            return "terms_unavailable"
        status, _, body = response
        if status != 200:
            return "terms_unavailable"
        if hashlib.sha256(body).hexdigest() != REVIEWED_TERMS:
            return "terms_changed"
        return None


def empty_result(status):
    return {"status": status, **dict.fromkeys(FIELDS), "field_sources": {}}


class Navigation:
    def __init__(self, page, rules, url):
        self.page = page
        self.rules = rules
        self.url = url
        self.current = url
        self.agent = page.evaluate("navigator.userAgent")
        self.pending = None
        self.http_status = None
        self.failure = None
        self.redirects = []
        self.denied = Counter()
        self.request_count = 0
        self.deadline = time.monotonic() + PAGE_SECONDS

    def abort(self, route, reason, main):
        if main:
            self.failure = self.failure or reason
        else:
            self.denied[(approved_host(route.request.url) or "other", reason)] += 1
        route.abort("blockedbyclient")

    def route(self, route):
        request = route.request
        try:
            main = request.is_navigation_request() and request.frame == self.page.main_frame
        except Error:
            main = False
        url = request.url
        if request.resource_type == "document" and (not main or url != self.current):
            reason = self.rules.decision(url, self.agent) if main else None
            self.abort(route, reason or "document_outside_probe", main)
            return
        if request.method not in {"GET", "HEAD"} or request.resource_type in {"ping", "eventsource"}:
            self.abort(route, "method_or_resource_outside_probe", main)
            return
        for index in range(MAX_REDIRECTS + 1):
            remaining = self.deadline - time.monotonic()
            if self.failure or self.request_count >= REQUEST_LIMIT or remaining <= 0:
                self.abort(route, self.failure or "request_budget_exceeded", main)
                return
            reason = self.rules.decision(url, self.agent)
            if reason:
                self.abort(route, reason, main)
                return
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                self.abort(route, "request_budget_exceeded", main)
                return
            self.request_count += 1
            try:
                response = route.fetch(url=url, max_redirects=0, max_retries=0,
                                       timeout=max(1, int(1000 * min(remaining, 8))))
            except Error:
                self.abort(route, "transport_error", main)
                return
            try:
                status = response.status
                if main:
                    self.http_status = status
                if status in REDIRECTS:
                    try:
                        destination = urljoin(url, response.headers.get("location", ""))
                    except ValueError:
                        destination = ""
                    reason = self.rules.decision(destination, self.agent)
                    if main:
                        self.redirects.append({
                            "http_status": status, "destination_host": approved_host(destination),
                            "destination_article": article_address(destination), "policy": reason,
                        })
                    if reason or index == MAX_REDIRECTS:
                        self.abort(route, reason or "redirect_limit", main)
                        return
                    if main and destination != url and article_address(destination) == self.url:
                        # Let the current navigation finish before starting the approved hop.
                        # Never deliver a redirect header that Chromium could follow unchecked.
                        self.pending = destination
                        route.fulfill(status=200, content_type="text/html", body="")
                        return
                    if main or destination == url or approved_host(destination) != approved_host(url):
                        self.abort(route, "redirect_outside_probe", main)
                        return
                    url = destination
                    continue
                if status in ACCESS_ERRORS:
                    self.abort(route, f"http_{status}", main)
                    return
                body = response.body()
                if len(body) > LIMIT:
                    self.abort(route, "resource_too_large", main)
                    return
                # route.fetch decodes HTTP encodings and handles anonymous session cookies.
                headers = {key: value for key, value in response.headers.items()
                           if key.lower() not in {"connection", "content-encoding", "content-length",
                                                  "set-cookie", "transfer-encoding"}}
                route.fulfill(status=status, headers=headers, body=body)
                return
            except Error:
                self.abort(route, "response_render_error", main)
                return
            finally:
                response.dispose()

    def open(self):
        for _ in range(MAX_REDIRECTS + 1):
            try:
                self.page.goto(self.current, wait_until="domcontentloaded", timeout=12_000)
            except Error:
                return self.failure or "navigation_failed"
            if not self.pending:
                return self.failure
            self.current, self.pending = self.pending, None
        return "redirect_limit"

    def record(self):
        return {
            "status": self.failure or "document_loaded",
            "http_status": self.http_status,
            "final_url": article_address(self.page.url) if self.http_status == 200 else None,
            "redirects": self.redirects,
            "blocked_resources": [
                {"host": host, "reason": reason, "requests": count}
                for (host, reason), count in sorted(self.denied.items())
            ],
        }


ARTICLE_DOM = r"""
() => {
    const text = node => node?.innerText?.trim().replace(/\s+/g, " ") || null;
    const visible = node => node && node.getClientRects().length &&
        getComputedStyle(node).visibility === "visible";
    const h1 = [...document.querySelectorAll("h1")].find(visible);
    const main = h1?.closest("article, main, [role=main]") || document.body;
    const meta = key => document.querySelector('meta[property="' + key + '"]')?.content || null;
    const declared = document.querySelector('link[rel=canonical]')?.href || meta("og:url");
    let sameArticle = false;
    try {
        const url = new URL(declared, location.href);
        sameArticle = !!declared && url.origin === location.origin && url.pathname === location.pathname;
    } catch {}
    if (!h1 || !sameArticle || ![...main.querySelectorAll("p")].some(
            node => visible(node) && (text(node)?.length || 0) >= 35)) {
        const heading = [document.title, text(h1), document.body?.innerText?.slice(0, 250)].join(" ");
        if (/подтвердите,? что (вы )?не робот|проверка браузера|captcha|verify you are human|unusual traffic/i.test(heading))
            return {status: "challenge_visible"};
        if (/войдите,? чтобы (читать|продолжить)|вход в аккаунт|вход в дзен|sign in to continue/i.test(heading))
            return {status: "login_visible"};
        return {status: "article_not_confirmed"};
    }
    let header = h1.closest("header") || h1.parentElement;
    if (!h1.closest("header")) {
        for (let i = 0; i < 4 && header.parentElement && header.parentElement !== main; i++) {
            if (header.parentElement.querySelectorAll("h1").length !== 1) break;
            header = header.parentElement;
        }
    }
    const count = (nodes, pattern) => {
        const values = new Set();
        for (const node of nodes) {
            if (!visible(node)) continue;
            for (const label of [node.getAttribute("aria-label"), node.title, text(node)]) {
                if (!label || label.length > 70) continue;
                const match = label.match(pattern);
                const number = match?.[1] || match?.[2];
                if (number) values.add(Number(number.replace(/\s/g, "")));
            }
        }
        const number = [...values][0];
        return values.size === 1 && Number.isSafeInteger(number) ? number : null;
    };
    const labels = [...header.querySelectorAll("[aria-label], [title], button, span")];
    const panel = [...document.querySelectorAll("h2, h3, [role=heading]")].find(node =>
        visible(node) && /^Комментарии(?:\s*\(\d[\d\s]*\))?$/i.test(text(node) || ""));
    const time = [...header.querySelectorAll("time")].find(visible);
    const channel = [...header.querySelectorAll('a[rel=author], [itemprop=author], [data-testid*="channel-name"]')]
        .find(visible);
    const relative = [...header.querySelectorAll("span")].filter(visible).map(text).find(label =>
        label && /^(?:сегодня|вчера|\d+ (?:мин|ч|д|нед|мес|лет)(?:\s+назад)?)$/i.test(label));
    const structuredDates = new Set();
    for (const node of [...document.querySelectorAll('script[type="application/ld+json"]')].slice(0, 8)) {
        const source = node.textContent;
        if (!source || source.length > 100000) continue;
        try {
            const parsed = JSON.parse(source);
            const entries = Array.isArray(parsed) ? parsed : (parsed["@graph"] || [parsed]);
            for (const item of entries) {
                if (item?.headline?.trim() === text(h1) && typeof item.datePublished === "string")
                    structuredDates.add(item.datePublished);
            }
        } catch {}
    }
    return {
        status: "article_rendered", title: text(h1), channel: text(channel),
        time_datetime: time?.dateTime || null, published_label: text(time) || relative || null,
        published_meta: meta("article:published_time"),
        structured_date: structuredDates.size === 1 ? [...structuredDates][0] : null,
        views: count(labels, /^(?:(\d[\d\s]*) просмотр(?:а|ов)?|просмотров:\s*(\d[\d\s]*))$/i),
        subscribers: count(labels, /^(?:(\d[\d\s]*) подписчик(?:а|ов)?|подписчиков:\s*(\d[\d\s]*))$/i),
        comments_visible: panel ? true : null,
        comment_count: count([panel, ...labels],
            /^(?:(\d[\d\s]*) комментар(?:ий|ия|иев)|Комментарии[: (]+(\d[\d\s]*)\)?)$/i),
    };
}
"""


def publication_date(value):
    if not value or not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|T)", value):
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value).isoformat()
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def probe_article(browser, rules, url):
    with browser.new_context(service_workers="block", accept_downloads=False,
                             java_script_enabled=True) as context:
        page = context.new_page()
        nav = Navigation(page, rules, url)
        context.route("**/*", nav.route)
        context.route_web_socket("**/*", lambda socket: socket.close())
        nav.failure = nav.open()
        if nav.failure or nav.http_status != 200:
            nav.failure = nav.failure or "unexpected_document_response"
            return nav.record(), empty_result("not_extracted")
        try:
            page.locator("h1").first.wait_for(state="visible", timeout=5_000)
        except Error:
            pass
        try:
            data = page.evaluate(ARTICLE_DOM)
            if data["status"] == "article_rendered" and not data["comments_visible"]:
                buttons = page.get_by_role("button", name=re.compile(
                    r"^(?:Открыть )?комментарии(?:\s*\(\d[\d\s]*\))?$", re.I)).filter(visible=True)
                if buttons.count() == 1:
                    try:
                        buttons.click(timeout=1500)
                        page.get_by_role("heading", name=re.compile(r"^Комментарии(?:\s|\(|$)", re.I)).first.wait_for(
                            state="visible", timeout=2500)
                    except Error:
                        pass
                    data = page.evaluate(ARTICLE_DOM)
        except Error:
            data = {"status": "render_error"}
        if nav.failure or article_address(page.url) != url or data["status"] != "article_rendered":
            nav.failure = nav.failure or (
                data["status"] if data["status"] != "article_rendered" else "article_identity_unconfirmed"
            )
            return nav.record(), empty_result("not_extracted")
        result = empty_result("article_rendered")
        result.update({field: data[field] for field in FIELDS if field in data})
        result["final_url"] = url
        for field in ("title", "channel", "published_label", "views", "subscribers",
                      "comments_visible", "comment_count"):
            if result[field] is not None:
                result["field_sources"][field] = "visible_article_dom"
        for key, source in (("time_datetime", "visible_time_datetime"),
                            ("published_meta", "article:published_time"),
                            ("structured_date", "matching_json_ld_datePublished")):
            exact = publication_date(data[key])
            if exact:
                result["published_at"] = exact
                result["field_sources"]["published_at"] = source
                break
        return nav.record(), result


def run_probe():
    rules = SiteRules()
    report = {
        "stage": "A.2", "diagnostic_version": DIAGNOSTIC_VERSION,
        "started_at_utc": timestamp(), "status": "not_run",
        "browser": None, "robots_http": rules.audit, "policy_fetches": rules.fetches,
        "results": [
            {"control": name, "role": role, "url": url,
             "ordinary_browser": empty_result("not_observed"),
             "controlled_browser": {"status": "not_run", "http_status": None, "final_url": None},
             "automated_extraction": empty_result("not_extracted")}
            for name, role, url in CONTROLS
        ],
    }
    denied = rules.check_terms()
    if denied:
        report.update(status=denied, finished_at_utc=timestamp())
        return report
    with sync_playwright() as playwright:
        for channel in ("chrome", "msedge"):
            try:
                browser = playwright.chromium.launch(
                    channel=channel, headless=False, chromium_sandbox=True)
                break
            except Error:
                pass
        else:
            report.update(status="browser_unavailable", finished_at_utc=timestamp())
            return report
        report["browser"] = {"channel": channel, "version": browser.version, "java_script": True}
        try:
            for index, row in enumerate(report["results"]):
                if index:
                    time.sleep(2)
                try:
                    navigation, extraction = probe_article(browser, rules, row["url"])
                except Error:
                    navigation = {"status": "browser_error", "http_status": None, "final_url": None}
                    extraction = empty_result("not_extracted")
                row["controlled_browser"] = navigation
                row["automated_extraction"] = extraction
                if navigation["status"] in {"login_visible", "challenge_visible", "http_401", "http_403", "http_429"}:
                    report["stop_reason"] = navigation["status"]
                    break
        finally:
            browser.close()
    rows = [row["automated_extraction"] for row in report["results"]]
    report.update(
        status="finished", finished_at_utc=timestamp(),
        articles_rendered=sum(row["status"] == "article_rendered" for row in rows),
        articles_with_date_and_discussion=sum(
            row["published_at"] is not None and (row["comment_count"] is not None or row["comments_visible"] is True)
            for row in rows
        ),
        articles_with_date_views_and_positive_comments=sum(
            row["published_at"] is not None and row["views"] is not None
            and row["comment_count"] is not None and row["comment_count"] > 0 for row in rows
        ),
    )
    return report


def save_report(report, path):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def show_app(path):
    import tkinter as tk
    from tkinter import ttk

    window = tk.Tk()
    window.title(f"Дзен · проверка доступности A.2 · версия {DIAGNOSTIC_VERSION}")
    window.minsize(570, 290)
    panel = ttk.Frame(window, padding=20)
    panel.pack(fill="both", expand=True)
    ttk.Label(panel, text="Проверка доступности Дзена", font=("Segoe UI", 16)).pack(anchor="w")
    ttk.Label(panel, text="Три контрольные статьи. Chrome или Edge использует отдельный профиль.",
              wraplength=530).pack(anchor="w", pady=(8, 12))
    status = tk.StringVar(value="Готово к проверке.")
    choices = []
    report = None
    executor = ThreadPoolExecutor(max_workers=1)

    def write_report(_event=None):
        if report is None:
            return True
        for choice, row in zip(choices, report["results"]):
            row["ordinary_browser"]["status"] = MANUAL_STATUSES[choice.get()]
        try:
            save_report(report, path)
        except OSError:
            status.set("Отчёт не сохранён. Распакуйте архив в папку, доступную для записи.")
            return False
        return True

    def finish(future):
        nonlocal report
        if not future.done():
            window.after(150, finish, future)
            return
        button.configure(state="normal")
        try:
            report = future.result()
        except (Error, OSError, ValueError):
            status.set("Браузер или сеть недоступны. Закройте окно и повторите запуск.")
            return
        messages = {
            "browser_unavailable": "Не удалось запустить Chrome или Edge.",
            "terms_changed": "Редакция условий Дзена изменилась. Нужна проверка правил.",
            "terms_unavailable": "Условия Дзена недоступны.",
            "robots_unavailable": "Правила robots.txt недоступны.",
            "robots_denied": "Запрос остановлен по robots.txt.",
            "finished": f"Проверка завершена. Открыто статей: {report.get('articles_rendered', 0)} из 3.",
        }
        if write_report():
            status.set(messages.get(report["status"], "Запрос остановлен правилами.") +
                       f" Отправьте файл {REPORT_NAME} из этой папки.")

    def start():
        button.configure(state="disabled")
        status.set("Проверяются правила и статьи. Дождитесь завершения.")
        finish(executor.submit(run_probe))

    button = ttk.Button(panel, text="Проверить доступность", command=start)
    button.pack(anchor="w")
    ttk.Label(panel, textvariable=status, wraplength=530).pack(anchor="w", pady=(10, 12))
    ttk.Separator(panel).pack(fill="x")
    ttk.Label(panel, text="Ручное сравнение (по желанию)").pack(anchor="w", pady=(8, 4))
    for name, _, url in CONTROLS:
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=2)
        link = ttk.Label(row, text=name, foreground="#1558A4", cursor="hand2")
        link.pack(side="left")
        link.bind("<Button-1>", lambda _, target=url: webbrowser.open_new_tab(target))
        choice = tk.StringVar(value="Не проверял")
        choices.append(choice)
        menu = ttk.Combobox(row, textvariable=choice, values=list(MANUAL_STATUSES), state="readonly", width=28)
        menu.pack(side="right")
        menu.bind("<<ComboboxSelected>>", write_report)
    window.protocol("WM_DELETE_WINDOW", lambda: window.destroy() if button.instate(["!disabled"]) else None)
    try:
        window.mainloop()
    finally:
        executor.shutdown(wait=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-window", action="store_true", help="Run without the diagnostic launcher")
    args = parser.parse_args()
    report_path = Path(__file__).resolve().with_name(REPORT_NAME)
    if args.no_window:
        save_report(run_probe(), report_path)
    else:
        show_app(report_path)


if __name__ == "__main__":
    main()
