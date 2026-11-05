#!/usr/bin/env python3
"""GitHub-only HPII editorial queue dashboard, never published to GitHub Pages.

This repository is public; GitHub Markdown is a technical view, NOT private.
"""
import argparse
import datetime as dt
from html import escape
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.site_first_release_pr import COVER, STORY, exists_at, git, safe_git_blob_at
from scripts.site_publication_queue import (
    INTERVAL, SITE_TZ, _last_change, latest_site_first_publication, parse_slot
)

REPO = "https://github.com/AfterDark1000/iipike-site"
SITE = "https://iipike.ru"
MAIN = "origin/main"
INBOX = "origin/editorial-intake"


def safe_text(raw, limit=200):
    if not isinstance(raw, str):
        return "—"
    return (escape(" ".join(raw.split())[:limit], quote=True)
            .replace("|", "&#124;").replace("[", "&#91;").replace("]", "&#93;"))


def site_local(moment):
    if not moment:
        return "—"
    if isinstance(moment, str):
        moment = dt.datetime.fromisoformat(moment.replace("Z", "+00:00"))
    return moment.astimezone(SITE_TZ).strftime("%d.%m.%Y %H:%M")


def scan_queue(main=MAIN, inbox=INBOX, *, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if not now.tzinfo:
        raise ValueError("Queue dashboard needs an offset-aware time")
    paths = git("ls-tree", "-r", "--name-only", inbox, "--",
                "editorial_inbox/stories", "editorial_inbox/covers").stdout.splitlines()
    stories, covers = {}, {}
    for path in paths:
        story = STORY.fullmatch(path)
        art = COVER.fullmatch(path)
        if story:
            stories[story[1]] = path
        elif art:
            covers.setdefault(art[1], []).append(path)
    catalog = json.loads(safe_git_blob_at(main, "news.json"))
    public = {r["id"]: r for r in catalog}
    last = latest_site_first_publication(catalog, main_ref=main)
    spacing_until = last + INTERVAL if last and now < last + INTERVAL else None
    rows = []
    for sid, path in sorted(stories.items()):
        raw = safe_git_blob_at(inbox, path)
        if len(raw) > 128_000:
            raise ValueError("Oversized editorial story: " + sid)
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("id") != sid:
            raise ValueError("Invalid editorial story ID: " + sid)
        scheduled = parse_slot(data["site_publish_at"]) if "site_publish_at" in data else None
        page = exists_at(main, "articles/" + sid + "/index.html")
        published = public.get(sid)
        arts = covers.get(sid, [])
        if bool(page) != bool(published):
            status = "⚠️ Несогласованный выпуск"
        elif page:
            status = "✅ Опубликована"
        elif data.get("status") != "editor_approved" or data.get("approved_by") != "human_editor":
            status = "⛔ Не утверждена"
        elif len(arts) > 1:
            status = "⚠️ Несколько обложек"
        elif not arts:
            status = "🖼️ Ждёт обложку"
        elif scheduled and now < scheduled:
            status = "🕒 Ожидает заданного времени"
        elif spacing_until:
            status = "⏳ Ждёт часовой интервал"
        else:
            status = "🟢 Готова к выпуску"
        ready_at = (max(_last_change(inbox, path), _last_change(inbox, arts[0]))
                    if len(arts) == 1 and not page else None)
        rows.append({
            "id": sid,
            "title": data.get("title"),
            "status": status,
            "published": bool(page),
            "published_at": published.get("published_at_utc") if page else None,
            "ready_at": ready_at,
            "publish_at": scheduled,
            "spacing_until": spacing_until if status == "⏳ Ждёт часовой интервал" else None,
            "source_path": path,
            "cover_path": arts[0] if arts else None,
        })
    return rows, last


def as_markdown(rows, last):
    active = sum(r["status"] == "🟢 Готова к выпуску" for r in rows)
    held = sum(r["status"] == "⏳ Ждёт часовой интервал" for r in rows)
    waiting = sum(r["status"] == "🖼️ Ждёт обложку" for r in rows)
    future = sum(r["status"] == "🕒 Ожидает заданного времени" for r in rows)
    published = sum(r["published"] for r in rows)
    out = [
        "# ХПИИ — очередь публикаций на сайте",
        "",
        "> Служебный журнал GitHub, не страница iipike.ru. "
        "**Репозиторий публичный, поэтому содержимое журнала не является конфиденциальным.**",
        "",
        "**Готовы:** " + str(active) + " · **Ждут интервал:** " + str(held)
        + " · **Назначено время:** " + str(future) + " · **Ждут обложку:** " + str(waiting)
        + " · **Уже опубликованы:** " + str(published),
        "",
        "Планировщик проверяет очередь каждые 15 минут, выпускает максимум "
        "одну статью за запуск с интервалом не менее 60 минут. "
        "Фактическое время может сдвигаться из-за задержек GitHub Actions и Pages.",
        "",
        "Последний выпуск на сайте из редакционной очереди: "
        + ("**" + site_local(last) + " (Усть-Катав)**" if last else "ещё не обнаружен") + ".",
        "",
        "| Материал | Статус | Время | Обложка |",
        "|---|---|---|---|",
    ]
    priority = sorted(rows, key=lambda r: (
        r["published"],
        r["ready_at"] or dt.datetime.max.replace(tzinfo=dt.timezone.utc),
        r["id"],
    ))
    for r in priority:
        sid = r["id"]
        title = safe_text(r["title"])
        path = r["source_path"]
        if r["published"]:
            link = SITE + "/articles/" + sid + "/"
            label = site_local(r["published_at"])
        else:
            link = REPO + "/blob/editorial-intake/" + path
            label = ("не ранее " + site_local(r["publish_at"]) + " (Усть-Катав)"
                     if r["publish_at"] else "автоматическая очередь")
            if r.get("spacing_until"):
                label += "; пауза до " + site_local(r["spacing_until"]) + " (Усть-Катав)"
        cover = ("[Есть](" + REPO + "/blob/editorial-intake/" + r["cover_path"] + ")"
                 if r["cover_path"] else "Нет")
        out.append("| [" + title + "](" + link + ") | " + r["status"]
                   + " | " + label + " | " + cover + " |")
    if not rows:
        out.append("| Входящих материалов нет | — | — | — |")
    out.extend([
        "",
        "## Что означают статусы",
        "",
        "- **Готова к выпуску:** текст и обложка получены; точная минута "
        "не гарантирована, выпуск на следующем допустимом запуске.",
        "- **Ожидает заданного времени:** редактор указал время, раньше него выпуск запрещён.",
        "- **Ждёт часовой интервал:** предыдущая статья вышла недавно; время окончания паузы указано в таблице. После него выпуск возможен при следующем запуске планировщика.",
        "- **Ждёт обложку:** текст есть, но публикация не начнётся до получения изображения.",
        "- **Опубликована:** статья найдена и в каталоге, и среди публичных HTML страниц.",
        "- **Ошибка:** см. журналы планировщика и проверьте исходные файлы.",
        "",
        "**[Запуски планировщика](" + REPO
        + "/actions/workflows/site-first-scheduled-release.yml)** · "
        "**[Правила очереди](" + REPO
        + "/blob/main/editorial_inbox/SITE_PUBLICATION_QUEUE.md)**",
        "",
        "Журнал обновляется при изменении списка и статусов, "
        "поэтому время очередной проверки смотрите в GitHub Actions. "
        "Для настоящей приватной админки потребуется авторизация.",
        "",
    ])
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rows, last = scan_queue()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(as_markdown(rows, last), encoding="utf-8")
    print("QUEUE_DASHBOARD_ROWS:", len(rows), flush=True)


if __name__ == "__main__":
    main()
