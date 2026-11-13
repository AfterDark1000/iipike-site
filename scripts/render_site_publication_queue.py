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
from scripts.site_release_quarantine import existing_error
from scripts.site_publication_queue import (
    INTERVAL, SITE_TZ, _last_change, latest_site_first_publication, parse_slot,
    in_quiet_hours, published_collision, release_interval, RECOVERY_INTERVAL, RECOVERY_UNTIL
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
    backlog = sum(1 for sid in stories if sid not in public and len(covers.get(sid, [])) == 1)
    spacing = release_interval(
        now, backlog,
        [sid for sid in stories if sid not in public and len(covers.get(sid, [])) == 1])
    spacing_until = last + spacing if last and now < last + spacing else None
    verified_links = None
    rows = []
    for sid, path in sorted(stories.items()):
        try:
            raw = safe_git_blob_at(inbox, path)
            if len(raw) > 128_000:
                raise ValueError("Oversized editorial story: " + sid)
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("id") != sid:
                raise ValueError("Invalid editorial story ID: " + sid)
            scheduled = parse_slot(data["site_publish_at"]) if "site_publish_at" in data else None
            if data.get("site_queue") not in (None, "priority"):
                raise ValueError("Invalid site_queue (expected priority)")
            if scheduled and data.get("site_queue"):
                raise ValueError("A timed release cannot also join the priority queue")
            lane = ("timed" if scheduled else "priority"
                    if data.get("site_queue") == "priority" else "standard")
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            rows.append({
                "id": sid, "title": sid, "status": "⛔ Заблокирована: ошибка статьи",
                "published": False, "published_at": None, "eligible": False,
                "block_reason": "Ошибка структуры редакционного JSON: " + str(exc)[:250],
                "ready_at": None, "publish_at": None, "spacing_until": None,
                "source_path": path, "cover_path": None, "lane": "standard",
            })
            continue
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
            blocked = existing_error(inbox, {"id": sid, "cover": arts[0]},
                                     main_ref=main)
            if blocked:
                block_reason = "Ошибка проверки статьи: " + str(blocked.get("reason", ""))
            duplicate = published_collision(data, catalog) if not block_reason else None
            if duplicate:
                block_reason = ("Эта статья уже опубликована под тем же ID или заголовком: "
                                + str(duplicate.get("id")))
            if not block_reason and "article_markdown" in data:
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
                status = ("⛔ Заблокирована: ошибка статьи"
                          if block_reason.startswith("Ошибка проверки статьи:")
                          else "⛔ Заблокирована: дубль опубликованного материала"
                          if block_reason.startswith("Эта статья уже опубликована")
                          else "⛔ Заблокирована: некорректное оформление"
                          if block_reason.startswith("Некорректное оформление текста:")
                          else "⛔ Заблокирована: связи с Дзеном")
            else:
                eligible = True
                if lane == "timed":
                    status = ("🕒 Ожидает заданного времени"
                              if now < scheduled or now < ready_at
                              else "🕒 Назначенное время наступило")
                elif in_quiet_hours(now):
                    status = "🌙 Ночная пауза"
                elif spacing_until:
                    status = ("⏳ Ждёт ускоренный интервал"
                              if spacing == RECOVERY_INTERVAL else "⏳ Ждёт часовой интервал")
                elif lane == "priority":
                    status = "⚡ Срочная очередь — готова"
                else:
                    status = "🟢 Готова к выпуску"

        rows.append({
            "id": sid, "title": data.get("title"), "status": status,
            "published": bool(page), "published_at": published.get("published_at_utc") if published else None,
            "eligible": eligible, "block_reason": block_reason,
            "ready_at": ready_at, "publish_at": scheduled, "lane": lane,
            "spacing_until": spacing_until if status.startswith("⏳ Ждёт ") else None,
            "source_path": path, "cover_path": arts[0] if len(arts) == 1 else None,
        })
    return rows, last


def is_selectable(row):
    return row.get("eligible", row.get("status") in (
        "🟢 Готова к выпуску", "⏳ Ждёт часовой интервал",
        "⏳ Ждёт ускоренный интервал",
        "🕒 Ожидает заданного времени", "🕒 Назначенное время наступило",
        "⚡ Срочная очередь — готова", "🌙 Ночная пауза"))


# Keep in sync with the cron minutes in site-first-scheduled-release.yml.
# This is a forecast only; release itself stays in site_publication_queue.py.
CRON_MINUTES = frozenset((7, 22, 37, 52))


def next_cron_tick(when, *, allow_night=False):
    """Next theoretical scheduled run; real GitHub Actions runs may be late."""
    if not when.tzinfo:
        raise ValueError("Cron forecast requires a timezone")
    when = when.astimezone(dt.timezone.utc)
    minute = when.replace(second=0, microsecond=0)
    for offset in range(24 * 60 + 65):
        candidate = minute + dt.timedelta(minutes=offset)
        if (candidate.minute in CRON_MINUTES and candidate >= when
                and (allow_night or not in_quiet_hours(candidate))):
            return candidate
    raise RuntimeError("Could not find next scheduled check")


def forecast_order(rows, last, *, now=None):
    """Forecast three lanes without letting timed articles reset queue slots.

    Priority and standard share hourly slots; timed articles are independent
    and can land between them. This is only an estimate: GitHub cron may lag.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    if not now.tzinfo:
        raise ValueError("Forecast requires an offset-aware time")
    now = now.astimezone(dt.timezone.utc)
    pending = [r for r in rows if is_selectable(r)]
    timed = [r for r in pending if r.get("lane", "timed" if r.get("publish_at") else "standard")
             == "timed"]
    regular = [r for r in pending if r not in timed]
    regular.sort(key=lambda r: (
        0 if r.get("lane") == "priority" else 1,
        r["ready_at"], r["id"],
    ))
    timed.sort(key=lambda r: (r["publish_at"], r["ready_at"], r["id"]))
    spacing = release_interval(now, len(regular), [r["id"] for r in regular])
    queue_tick = (next_cron_tick(max(now, last + spacing))
                  if last else next_cron_tick(now))
    result = []
    after_previous = now
    while timed or regular:
        # The nearest requested clock time, regardless of night queue pause.
        fixed_tick = (
            next_cron_tick(max(after_previous, r["publish_at"], r["ready_at"]),
                           allow_night=True)
            if (r := timed[0]) else None
        ) if timed else None
        queue_candidate = None
        if regular:
            queue_tick = next_cron_tick(max(queue_tick, after_previous))
            ready_queued = [r for r in regular if r["ready_at"] <= queue_tick]
            if not ready_queued:
                queue_tick = next_cron_tick(max(queue_tick, min(
                    r["ready_at"] for r in regular)))
                ready_queued = [r for r in regular if r["ready_at"] <= queue_tick]
            if ready_queued:
                queue_candidate = ready_queued[0]
        if fixed_tick is not None and (queue_candidate is None or fixed_tick <= queue_tick):
            selected = timed.pop(0)
            tick = fixed_tick
            # If a fixed-time article occupies the same cron invocation,
            # the queue waits for the next runner, NOT another full hour.
            if regular and queue_tick <= tick:
                queue_tick = next_cron_tick(tick + dt.timedelta(seconds=1))
        elif queue_candidate is not None:
            selected = queue_candidate
            tick = queue_tick
            regular.remove(selected)
            queue_tick = next_cron_tick(tick + release_interval(
                tick, len(regular), [r["id"] for r in regular]))
        else:
            raise RuntimeError("Could not schedule ready queue or timed article")
        result.append((selected, tick))
        after_previous = tick + dt.timedelta(seconds=1)
    return result


def as_markdown(rows, last, *, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    planned = forecast_order(rows, last, now=now)
    released = sorted(
        (r for r in rows if r["status"] == "✅ Опубликована"),
        key=lambda r: (r["published_at"] or "", r["id"]), reverse=True,
    )
    attention = [r for r in rows if not is_selectable(r)
                 and r["status"] != "✅ Опубликована"]
    active = sum(r["status"] in ("🟢 Готова к выпуску", "⚡ Срочная очередь — готова",
                                 "🕒 Назначенное время наступило") for r in rows)
    held = sum(r["status"].startswith("⏳ Ждёт ") for r in rows)
    future = sum(r.get("lane") == "timed" and is_selectable(r) for r in rows)
    priority_count = sum(r.get("lane") == "priority" and is_selectable(r) for r in rows)
    quiet = sum(r["status"] == "🌙 Ночная пауза" for r in rows)
    covers = sum(r["status"] == "🖼️ Ждёт обложку" for r in rows)
    blocked = sum(r["status"].startswith("⛔ Заблокирована") for r in rows)
    out = [
        "# ХПИИ — очередь публикаций на сайте", "",
        "> Служебный журнал GitHub, не страница iipike.ru. "
        "**Репозиторий публичный, поэтому содержимое журнала не является конфиденциальным.**",
        "",
        "**В очереди:** " + str(len(planned)) + " · **Готовы:** " + str(active)
        + " · **Ждут интервал:** " + str(held)
        + " · **Срочная очередь:** " + str(priority_count)
        + " · **Назначено время:** " + str(future)
        + " · **Ночная пауза:** " + str(quiet)
        + " · **Ждут обложку:** " + str(covers)
        + " · **Заблокированы:** " + str(blocked)
        + " · **Опубликованы через site-first:** " + str(len(released)),
        "",
        "Проверка каждые 15 минут; не более одной статьи за запуск. "
        "Срочная очередь впереди обычной, вместе они делят часовые слоты. "
        "Выпуск по назначенному времени не сдвигает очередь. "
        + ("Временно ускоренный интервал до публикации Gemini для больниц "
           "(не дольше 12.11.2026 19:00 по Усть-Катаву); после неё — 60 минут. "
           if release_interval(now, len(planned), [r["id"] for r, _ in planned]) == RECOVERY_INTERVAL
           else "Стандартный интервал — 60 минут. ")
        + "Автоматический выпуск приостанавливается "
        "ежедневно с 01:00 до 07:00 (Усть-Катав), очередь сохраняется "
        "и продолжается утром. Порядок — по времени готовности текста "
        "и обложки, если не назначено более позднее время. **Прогноз — не обещание публикации "
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

    out += ["", "## Опубликованы через site-first — новые сверху", "",
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
        "- **Ждёт интервал:** после последнего выпуска не прошёл требуемый интервал "
        "(60 минут обычно; 30 минут во время ограниченного восстановления).",
        "- **Ночная пауза:** автоматические выпуски запрещены с 01:00 до 07:00 "
        "по Усть-Катаву; материал остаётся в очереди.",
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
