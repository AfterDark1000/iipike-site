"use strict";

(() => {
  const data = window.firstCarSnapshots;
  const panel = document.querySelector("#panel");
  const storageKey = "dzen-first-car-v1";
  const directArticle = /^https:\/\/dzen\.ru\/a\/[A-Za-z0-9_-]{16}$/;
  const channelLink = /^https:\/\/dzen\.ru\/[A-Za-z0-9_.-]+$/;
  const guruLink = /^https:\/\/dzen\.guru\/channels\/[A-Za-z0-9_.-]+$/;
  const clock = new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Asia/Yekaterinburg", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const integer = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
  const percent = new Intl.NumberFormat("ru-RU", { style: "percent", maximumFractionDigits: 1 });
  const minute = 60_000;
  const freshnessLimit = 15 * minute;
  const decisions = readDecisions();
  let view = "queue";

  function readDecisions() {
    try {
      const entries = JSON.parse(localStorage.getItem(storageKey) || "{}");
      return new Map(Object.entries(entries).filter(([, value]) => ["commented", "skipped"].includes(value)));
    } catch {
      document.querySelector("#storage-note").textContent = "Отметки хранятся в этой вкладке";
      return new Map();
    }
  }

  function storeDecisions() {
    try {
      localStorage.setItem(storageKey, JSON.stringify(Object.fromEntries(decisions)));
    } catch {
      document.querySelector("#storage-note").textContent = "Отметки хранятся в этой вкладке";
    }
  }

  function escapeText(value) {
    return String(value ?? "").replace(/[&<>"']/g, (symbol) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[symbol]);
  }

  function exactTime(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return null;
    const time = Date.parse(value);
    return Number.isFinite(time) ? time : null;
  }

  function dateLabel(value) {
    const time = exactTime(value);
    return time === null ? "Неизвестно" : clock.format(time);
  }

  function known(value, formatter = integer) {
    return Number.isFinite(value) && value >= 0 ? formatter.format(value) : "Неизвестно";
  }

  function minutesBetween(from, to) {
    return from !== null && to !== null && from <= to ? (to - from) / minute : null;
  }

  function ageLabel(age) {
    if (age === null) return "Неизвестно";
    const minutes = Math.floor(age);
    return minutes < 60 ? `${minutes} мин` : `${Math.floor(minutes / 60)} ч ${minutes % 60} мин`;
  }

  function status(label, tone = "") {
    return `<span class="badge ${tone}">${escapeText(label)}</span>`;
  }

  function field(label, value) {
    return `<div><dt>${escapeText(label)}</dt><dd>${escapeText(value)}</dd></div>`;
  }

  function link(url, label, pattern, classes = "") {
    const text = escapeText(label);
    return pattern.test(url) ?
      `<a class="${classes}" href="${escapeText(url)}" target="_blank" rel="noopener noreferrer">${text}</a>` : text;
  }

  function queueEntries(now) {
    return data.articles.filter((article) => {
      const author = data.channels.find((channel) => channel.slug === article.channel);
      const publication = exactTime(article.published_at);
      const firstSeen = exactTime(article.first_seen_at);
      const snapshot = exactTime(article.observed_at);
      const seenAge = minutesBetween(publication, firstSeen);
      const currentAge = minutesBetween(publication, now);
      return directArticle.test(article.url) && author?.status === "confirmed_candidate"
        && author.history?.verified === true && article.evidence === "verified"
        && article.ai === true && article.comments_open === true
        && Number.isInteger(article.comments) && article.comments >= 0 && article.comments <= 3
        && firstSeen !== null && snapshot !== null && firstSeen <= snapshot
        && now >= snapshot && now - snapshot <= freshnessLimit
        && seenAge !== null && seenAge <= 60 && currentAge !== null && currentAge <= 60;
    }).sort((a, b) => exactTime(b.published_at) - exactTime(a.published_at) || a.comments - b.comments);
  }

  function articleRow(article, demo = false) {
    const channel = demo ? article : data.channels.find((item) => item.slug === article.channel).history;
    const channelName = demo ? article.channel_name : data.channels.find((item) => item.slug === article.channel).name;
    const stored = decisions.get(`${view}|${article.url}`);
    const age = minutesBetween(exactTime(article.published_at), exactTime(article.first_seen_at));
    const decisionText = stored === "commented" ? "Прокомментировано" : "Пропущено";
    const button = (action, label) => `<button type="button" class="button" data-decision="${action}" data-url="${escapeText(article.url)}">${label}</button>`;
    const decisionButtons = stored ? button("undo", "Вернуть") :
      button("commented", "Прокомментировано") + button("skipped", "Пропустить");
    return `
      <article class="row">
        <div class="row-top"><span class="muted">${escapeText(channelName)}</span>
          ${status(stored ? decisionText : demo ? "Наблюдалось в архиве" : "Подтверждено", "observed")}</div>
        <h3>${link(article.url, article.title, directArticle)}</h3>
        <dl>
          ${field("Опубликовано", dateLabel(article.published_at))}
          ${field("Возраст при находке", ageLabel(age))}
          ${field("Комментарии в снимке", known(article.comments))}
          ${field("Просмотры в снимке", known(article.views))}
        </dl>
        <p class="details"><strong>История канала</strong> · медиана ${known(channel.median_views)} по ${known(channel.views_known)} ст.
          · с обсуждениями ${known(channel.discussion_rate, percent)}</p>
        <p class="details">${demo ? "Аудитория не подтверждена. Опубликовано за пределами окна." :
          age <= 30 ? "Найдена в первые 30 минут, обсуждение открыто." : "Найдена в первые 60 минут, обсуждение открыто."}</p>
        <p class="details">Снимок Дзена · ${dateLabel(article.observed_at)}${demo ? " · определение просмотров не сверено" : ""}</p>
        <div class="actions">${link(article.url, "Открыть", directArticle, "button primary")}${decisionButtons}</div>
      </article>`;
  }

  function queuePanel(now, entries, pending) {
    const latest = Math.max(...data.articles.map((item) => exactTime(item.observed_at) ?? -Infinity));
    const stale = Number.isFinite(latest) && now - latest > freshnessLimit;
    const source = stale ? `<div class="notice"><strong>Источник устарел</strong>
      <span>Последний снимок ${clock.format(latest)}.</span></div>` : "";
    const empty = `<div class="empty"><h2>Сейчас подходящих статей нет</h2>
      <p>${data.articles.length ? "По сохранённым данным нет новых статей, доступных для отбора." :
        "Для шести каналов нет сохранённых снимков последних публикаций. Пригодность их статей пока нельзя проверить."}</p>
      <button type="button" class="button" data-view="channels">Посмотреть каналы</button></div>`;
    const handled = entries.filter((article) => decisions.has(`queue|${article.url}`));
    return `<header class="panel-head"><h2>Очередь статей</h2><p>Ожидают отметки · ${pending.length}</p></header>
      ${source}${pending.length ? pending.map((article) => articleRow(article)).join("") : empty}
      ${handled.length ? `<details class="handled"><summary>Отмеченные · ${handled.length}</summary>
        ${handled.map((article) => articleRow(article)).join("")}</details>` : ""}`;
  }

  function channelPanel() {
    const labels = {
      confirmed_candidate: ["Подтверждён", "observed"],
      low_priority: ["Низкий приоритет", ""],
      insufficient_evidence: ["Недостаточно данных", ""],
    };
    const rows = data.channels.map((channel) => {
      const archive = channel.archive_records ?? [];
      const archived = archive.length ? `<p class="details">
        Архивных записей · ${archive.length}. С комментариями · ${archive.filter((article) => article.comments > 0).length}.
        </p>` : "";
      return `
      <article class="row">
        <div class="row-top">
          <h3>${link(channel.url, channel.name, channelLink)}</h3>
          ${status(...labels[channel.status])}
        </div>
        <dl>
          ${field("ИИ-статьи в Дзене", channel.ai_share ?? "Неизвестно")}
          ${field("Медиана ИИ-статей", known(channel.history?.median_views))}
          ${field("С обсуждениями", known(channel.history?.discussion_rate, percent))}
          ${field("Медиана Guru · справочно", known(channel.guru_median))}
        </dl>
        <p class="details">${escapeText(channel.reason)}</p>
        ${archived}
        ${link(channel.guru_url, "Публичная карточка Guru", guruLink, "evidence-link")}
      </article>`;
    }).join("");
    return `<header class="panel-head"><h2>Каналы для проверки</h2>
      <p>Данные Дзена и справочные показатели Guru.</p></header>${rows}`;
  }

  function demoPanel() {
    return `<header class="panel-head"><h2>Демо · архив реальных статей</h2>
      <p>Учебный режим для кнопок. Отметки сохраняются локально, без отправки в Дзен.</p></header>
      <div class="notice"><strong>Источник устарел</strong><span>
        Снимки от ${dateLabel(data.demo_observed_at)}. Карточки показаны для примера.</span></div>
      ${data.demo.map((article) => articleRow(article, true)).join("")}`;
  }

  function render() {
    const now = Date.now();
    const eligible = queueEntries(now);
    const pending = eligible.filter((article) => !decisions.has(`queue|${article.url}`));
    document.querySelector("#queue-count").textContent = pending.length;
    document.querySelector("#channel-count").textContent = data.channels.length;
    document.querySelectorAll(".navigation [data-view]").forEach((button) => {
      if (button.dataset.view === view) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    panel.innerHTML = view === "queue" ? queuePanel(now, eligible, pending) :
      view === "channels" ? channelPanel() : demoPanel();
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (["queue", "channels", "demo"].includes(button.dataset.view)) {
      view = button.dataset.view;
      render();
      document.querySelector(`.navigation [data-view="${view}"]`).focus();
    } else if (directArticle.test(button.dataset.url)) {
      const action = button.dataset.decision;
      const key = `${view}|${button.dataset.url}`;
      if (action === "undo") decisions.delete(key);
      else if (["commented", "skipped"].includes(action)) decisions.set(key, action);
      else return;
      storeDecisions();
      document.querySelector("#announcement").textContent = action === "undo" ?
        "Локальная отметка снята" : "Локальная отметка сохранена";
      render();
      const replacement = [...panel.querySelectorAll("button[data-url]")]
        .find((item) => item.dataset.url === button.dataset.url);
      if (replacement && replacement.getClientRects().length) replacement.focus();
      else document.querySelector(`.navigation [data-view="${view}"]`).focus();
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) render();
  });

  render();
})();
