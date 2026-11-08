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
from scripts.site_related import catalog_entries, validate_links, explicit_site_crosslinks
from scripts.site_rich_text import markdown_to_blocks
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
    """Inspect exactly what the publisher will consider, without releasing anything."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if not now.tzinfo:
        raise ValueError("Queue dashboard needs an offset-aware time")
    now = now.astimezone(dt.timezone.utc)
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
    verified_links = None
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
        ready_at = (max(_last_change(inbox, path), _last_change(inbox, arts[0]))
                    if len(arts) == 1 and not page else None)
        block_reason = None
        eligible = False

        if bool(page) != bool(published):
            status = "⚠️ Несогласованный выпуск"
            block_reason = "Публичная страница и каталог news.json не совпадают"
        elif page:
            status = "✅ Опубликована"
        elif data.get("status") != "editor_approved" or data.get("approved_by") != "human_editor":
            status = "⛔ Не утверждена"
            block_reason = "Нет подтверждённого редакторского одобрения"
        elif len(arts) > 1:
            status = "⚠️ Несколько обложек"
            block_reason = "Неоднозначный выбор обложки"
        elif not arts:
            status = "🖼️ Ждёт обложку"
        else:
            if "article_markdown" in data:
                try:
                    markdown_to_blocks(data["article_markdown"])
                except (ValueError, TypeError) as exc:
                    block_reason = "Некорректное оформление текста: " + str(exc)
            related = data.get("related_dzen_ids", [])
            if not block_reason and (related or data.get("site_crosslinks")):
                # Same crosslink validation as the scheduler, so its report
                # cannot falsely call a publishable story blocked.
                if verified_links is None:
                    verified_links = catalog_entries(ROOT)
                try:
                    mapped = explicit_site_crosslinks(data, catalog)
                    validate_links(related, verified_links,
                                   site_crosslinks=mapped)
                except ValueError as exc:
                    block_reason = str(exc)
            if block_reason:
                status = "⛔ Заблокирована: проверка материала"
            else:
                eligible = True
                if scheduled and now < scheduled:
                    status = "🕒 Ожидает заданного времени"
                elif spacing_until:
                    status = "⏳ Ждёт часовой интервал"
                else:
                    status = "🟢 Готова к выпуску"

        rows.append({
            "id": sid, "title": data.get("title"), "status": status,
            "published": bool(page), "published_at": published.get("published_at_utc") if published else None,
            "eligible": eligible, "block_reason": block_reason,
            "ready_at": ready_at, "publish_at": scheduled,
            "spacing_until": spacing_until if status == "⏳ Ждёт часовой интервал" else None,
            "source_path": path, "cover_path": arts[0] if len(arts) == 1 else None,
        })
    return rows, last


def is_selectable(row):
    return row.get("eligible", row.get("status") in (
        "🟢 Готова к выпуску", "⏳ Ждёт часовой интервал",
        "🕒 Ожидает заданного времени"))


# Keep in sync with the cron minutes in site-first-scheduled-release.yml.
# This is a forecast only; release itself stays in site_publication_queue.py.
CRON_MINUTES = frozenset((7, 22, 37, 52))


def next_cron_tick(when):
    """Next theoretical scheduled run; real GitHub Actions runs may be late."""
    if not when.tzinfo:
        raise ValueError("Cron forecast requires a timezone")
    when = when.astimezone(dt.timezone.utc)
    minute = when.replace(second=0, microsecond=0)
    for offset in range(65):
        candidate = minute + dt.timedelta(minutes=offset)
        if candidate.minute in CRON_MINUTES and candidate >= when:
            return candidate
    raise RuntimeError("Could not find next scheduled check")


def forecast_order(rows, last, *, now=None):
    """Simulate the publisher's readiness-order scan, skipping future slots.

    Never claims exact publication times: Pages and Actions may lag, and later
    arrivals, manual urgent releases or edits can change the actual sequence.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    if not now.tzinfo:
        raise ValueError("Forecast requires an offset-aware time")
    pending = sorted(
        (r for r in rows if is_selectable(r)),
        key=lambda r: (r["ready_at"], r["id"]),
    )
    tick = next_cron_tick(max(now.astimezone(dt.timezone.utc), last + INTERVAL)
                          if last else now)
    output = []
    while pending:
        selected = next(
            (r for r in pending if tick >= r["ready_at"] and
             (r["publish_at"] is None or tick >= r["publish_at"])),
            None,
        )
        if selected is None:
            first_eligible = min(max(r["ready_at"], r["publish_at"] or r["ready_at"])
                                 for r in pending)
            tick = next_cron_tick(max(tick + dt.timedelta(seconds=1), first_eligible))
            continue
        output.append((selected, tick))
        pending.remove(selected)
        tick = next_cron_tick(tick + INTERVAL)
    return output


def as_markdown(rows, last, *, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    planned = forecast_order(rows, last, now=now)
    released = sorted(
        (r for r in rows if r["status"] == "✅ Опубликована"),
        key=lambda r: (r["published_at"] or "", r["id"]), reverse=True,
    )
    attention = [r for r in rows if not is_selectable(r)
                 and r["status"] != "✅ Опубликована"]
    active = sum(r["status"] == "🟢 Готова к выпуску" for r in rows)
    held = sum(r["status"] == "⏳ Ждёт часовой интервал" for r in rows)
    future = sum(r["status"] == "🕒 Ожидает заданного времени" for r in rows)
    covers = sum(r["status"] == "🖼️ Ждёт обложку" for r in rows)
    blocked = sum(r["status"].startswith("⛔ Заблокирована") for r in rows)
    out = [
        "# ХПИИ — очередь публикаций на сайте", "",
        "> Служебный журнал GitHub, не страница iipike.ru. "
        "**Репозиторий публичный, поэтому содержимое журнала не является конфиденциальным.**",
        "",
        "**В очереди:** " + str(len(planned)) + " · **Готовы:** " + str(active)
        + " · **Ждут интервал:** " + str(held)
        + " · **Назначено время:** " + str(future)
        + " · **Ждут обложку:** " + str(covers)
        + " · **Заблокированы:** " + str(blocked)
        + " · **Уже опубликованы:** " + str(len(released)),
        "",
        "Проверка каждые 15 минут; не более одной статьи за запуск с интервалом "
        "не менее 60 минут. Порядок — по времени готовности текста и обложки, "
        "если не назначено более позднее время. **Прогноз — не обещание публикации "
        "в указанную минуту:** GitHub Actions, Pages, ручные срочные выпуски и "
        "новые материалы могут его изменить.",
        "",
        "Последний выпуск на сайте из редакционной очереди: "
        + ("**" + site_local(last) + " (Усть-Катав)**" if last else "ещё не обнаружен") + ".",
        "",
        "## Следующие выпуски — прогноз по текущей очереди", "",
        "| № | Материал | Статус | Ориентир / ограничение | Обложка |",
        "|---:|---|---|---|---|",
    ]
    for position, (r, tick) in enumerate(planned, 1):
        link = REPO + "/blob/editorial-intake/" + r["source_path"]
        label = "**Не ранее " + site_local(tick) + " (Усть-Катав)**"
        if r.get("publish_at"):
            label += "; назначено не ранее " + site_local(r["publish_at"]) + " (Усть-Катав)"
        if r.get("spacing_until"):
            label += "; пауза до " + site_local(r["spacing_until"]) + " (Усть-Катав)"
        cover = ("[Есть](" + REPO + "/blob/editorial-intake/" + r["cover_path"] + ")"
                 if r["cover_path"] else "Нет")
        out.append("| **" + str(position) + "** | [" + safe_text(r["title"]) + "](" + link
                   + ") | " + r["status"] + " | " + label + " | " + cover + " |")
    if not planned:
        out.append("| — | Готовых к выбору материалов нет | — | — | — |")

    out += ["", "## Требуют внимания — не участвуют в выборе", "",
            "| Материал | Состояние | Причина | Обложка |",
            "|---|---|---|---|"]
    for r in attention:
        link = REPO + "/blob/editorial-intake/" + r["source_path"]
        reason = safe_text(r.get("block_reason") or "Текст или обложка ещё не готовы")
        cover = ("[Есть](" + REPO + "/blob/editorial-intake/" + r["cover_path"] + ")"
                 if r["cover_path"] else "Нет")
        out.append("| [" + safe_text(r["title"]) + "](" + link + ") | "
                   + r["status"] + " | " + reason + " | " + cover + " |")
    if not attention:
        out.append("| — | Нет проблемных материалов | — | — |")

    out += ["", "## Уже опубликованы — новые сверху", "",
            "| Материал | Время выхода (Усть-Катав) | Обложка |",
            "|---|---|---|"]
    for r in released:
        cover = ("[Есть](" + REPO + "/blob/editorial-intake/" + r["cover_path"] + ")"
                 if r["cover_path"] else "Нет")
        out.append("| [" + safe_text(r["title"]) + "](" + SITE + "/articles/"
                   + r["id"] + "/) | " + site_local(r["published_at"]) + " | " + cover + " |")
    if not released:
        out.append("| — | Опубликованных статей ещё нет | — |")

    out.extend([
        "", "## Что означают статусы", "",
        "- **Готова к выпуску:** утверждённый текст и обложка; время зависит от очереди.",
        "- **Ждёт часовой интервал:** после последнего выпуска не прошло 60 минут.",
        "- **Ожидает заданного времени:** редактор назначил ограничение «не раньше».",
        "- **Заблокирована:** автоматический выпуск пропускает материал из-за "
        "проверки редакционных связей (причина показана отдельно).",
        "- **Ждёт обложку / не утверждена / несогласованный выпуск:** "
        "не участвует в автоматической очереди до устранения проблемы.",
        "- **Опубликована:** подтверждена публичной страницей и каталогом news.json.",
        "",
        "**[Запуски планировщика](" + REPO
        + "/actions/workflows/site-first-scheduled-release.yml)** · "
        "**[Правила очереди](" + REPO
        + "/blob/main/editorial_inbox/SITE_PUBLICATION_QUEUE.md)**",
        "",
        "Журнал обновляется при проверках планировщика. Фактическое время "
        "выхода смотрите в опубликованной статье; права на администрирование "
        "этот публичный отчёт не предоставляет.", "",
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
