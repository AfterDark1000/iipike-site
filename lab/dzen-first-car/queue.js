"use strict";

(() => {
  const data = window.firstCarSnapshots;
  const panel = document.querySelector("#panel");
  const storageKey = "dzen-first-car-v1";
  const directArticle = /^https:\/\/dzen\.ru\/a\/[A-Za-z0-9_-]{16}$/;
  const channelLink = /^https:\/\/dzen\.ru\/(?:[A-Za-z0-9_.-]+|id\/[a-f0-9]{24})$/;
  const guruLink = /^https:\/\/dzen\.guru\/channels\/[A-Za-z0-9_.-]+$/;
  const clock = new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Asia/Yekaterinburg", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const integer = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
  const percent = new Intl.NumberFormat("ru-RU", { style: "percent", maximumFractionDigits: 1 });
  const minute = 60_000;
  const freshnessLimit = 15 * minute;
  const signalWindow = 60 * minute;
  const signals = data.signals ?? [];
  const decisions = readDecisions();
  if (data.bridge) {
    for (const key of decisions.keys()) if (key.startsWith("queue|")) decisions.delete(key);
    for (const [url, action] of Object.entries(data.decisions)) decisions.set(`queue|${url}`, action);
    document.querySelector("#storage-note").textContent = "Отметки очереди хранятся в локальной истории";
  }
  if (data.replay) {
    document.querySelector(".local").textContent = "Демо · тестовый прогон";
  }
  let view = "queue";
  let signalTimer;

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
          ${status(stored ? decisionText : demo ? "Наблюдалось в архиве" :
            data.replay ? "Тестовая карточка" : "Подтверждено", "observed")}</div>
        <h3>${data.replay && !demo ? escapeText(article.title) : link(article.url, article.title, directArticle)}</h3>
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
        <p class="details">${data.replay && !demo ? "Тестовый снимок" :
          escapeText(article.source || "Снимок Дзена")} · ${dateLabel(article.observed_at)}
          ${demo ? " · определение просмотров не сверено" : ` · впервые ${dateLabel(article.first_seen_at)}`}</p>
        <div class="actions">${data.replay && !demo ? "" : link(article.url, "Открыть", directArticle, "button primary")}${decisionButtons}</div>
      </article>`;
  }

  function queuePanel(now, entries, pending) {
    const latest = exactTime(data.latest_observed_at) ??
      Math.max(...data.articles.map((item) => exactTime(item.observed_at) ?? -Infinity));
    const stale = Number.isFinite(latest) && now - latest > freshnessLimit;
    const source = stale ? `<div class="notice"><strong>Источник устарел</strong>
      <span>Последний снимок ${clock.format(latest)}.</span></div>` : "";
    const empty = `<div class="empty"><h2>Сейчас подходящих статей нет</h2>
      <p>${data.bridge || data.articles.length ? "По сохранённым данным нет новых статей, доступных для отбора." :
        "Для шести каналов нет сохранённых снимков последних публикаций. Пригодность их статей пока нельзя проверить."}</p>
      <button type="button" class="button" data-view="channels">Посмотреть каналы</button></div>`;
    const handled = entries.filter((article) => decisions.has(`queue|${article.url}`));
    return `<header class="panel-head"><h2>Очередь статей</h2><p>Ожидают отметки · ${pending.length}</p></header>
      ${source}${pending.length ? pending.map((article) => articleRow(article)).join("") : empty}
      ${handled.length ? `<details class="handled"><summary>Отмеченные · ${handled.length}</summary>
        ${handled.map((article) => articleRow(article)).join("")}</details>` : ""}`;
  }

  function signalRow(signal) {
    const button = (action, label) => `<button type="button" class="button" data-decision="${action}" data-url="${escapeText(signal.url)}">${label}</button>`;
    const decision = signal.action === "commented" ? "Прокомментировано" : "Проверил/не подходит";
    return `<article class="row">
      <div class="row-top">${status("Не подтверждено", "stale")}${signal.action ? status(decision) : ""}</div>
      <h3>${escapeText(signal.title)}</h3>
      <dl>
        ${field("Ссылка обнаружена", dateLabel(signal.detected_at))}
        ${field("Опубликовано в Дзене", dateLabel(signal.dzen_published_at))}
        ${field("Комментарии Дзена", known(signal.dzen_comments))}
      </dl>
      ${link(signal.source_url, "Источник ссылки", /^https:\/\//, "evidence-link")}
      <div class="actions">
        ${link(signal.url, "Открыть в Дзене", directArticle, "button primary")}
        ${signal.action ? "" : button("checked", "Проверил/не подходит") + button("commented", "Прокомментировано")}
      </div>
    </article>`;
  }

  function signalPanel(pending, handled) {
    const empty = `<div class="empty"><h2>Свежих разведсигналов нет</h2></div>`;
    return `<header class="panel-head"><h2>Разведсигналы</h2>
      <p>Прямые ссылки для ручной проверки. Видны до часа после обнаружения.</p></header>
      ${pending.length ? pending.map(signalRow).join("") : empty}
      ${handled.length ? `<details class="handled"><summary>Отмеченные · ${handled.length}</summary>
        ${handled.map(signalRow).join("")}</details>` : ""}`;
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
          ${channel.stale ? status("Источник устарел", "stale") : status(...labels[channel.status])}
        </div>
        <dl>
          ${field("ИИ-статьи в Дзене", channel.ai_share ?? "Неизвестно")}
          ${field(data.bridge ? "Медиана общего потока" : "Медиана ИИ-статей", known(channel.history?.median_views))}
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
    const now = data.replay ? exactTime(data.as_of) : Date.now();
    const eligible = queueEntries(now);
    const pending = eligible.filter((article) => !decisions.has(`queue|${article.url}`));
    const currentSignals = signals.filter((signal) => {
      const seen = exactTime(signal.detected_at);
      return signal.verified === false && directArticle.test(signal.url) && seen !== null
        && seen <= now && now - seen <= signalWindow;
    });
    const pendingSignals = currentSignals.filter((signal) => !signal.action);
    document.querySelector("#queue-count").textContent = pending.length;
    document.querySelector("#signal-count").textContent = pendingSignals.length;
    document.querySelector("#channel-count").textContent = data.channels.length;
    document.querySelectorAll(".navigation [data-view]").forEach((button) => {
      if (button.dataset.view === view) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    panel.innerHTML = view === "queue" ? queuePanel(now, eligible, pending) :
      view === "signals" ? signalPanel(pendingSignals, currentSignals.filter((signal) => signal.action)) :
      view === "channels" ? channelPanel() : demoPanel();
    clearTimeout(signalTimer);
    if (view === "signals" && !data.replay && currentSignals.length) {
      const oldest = exactTime(currentSignals[currentSignals.length - 1].detected_at);
      signalTimer = setTimeout(render, oldest + signalWindow - now + 1);
    }
  }

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (["queue", "signals", "channels", "demo"].includes(button.dataset.view)) {
      view = button.dataset.view;
      render();
      document.querySelector(`.navigation [data-view="${view}"]`).focus();
    } else if (directArticle.test(button.dataset.url)) {
      const action = button.dataset.decision;
      const key = `${view}|${button.dataset.url}`;
      const signal = view === "signals" && signals.find((item) => item.url === button.dataset.url);
      const bridge = data.bridge && (view === "queue" || Boolean(signal));
      if (bridge) {
        const actions = button.closest(".actions").querySelectorAll("button");
        actions.forEach((item) => { item.disabled = true; });
        try {
          const response = await fetch(signal ? "/signal-decision" : "/decision", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: button.dataset.url, action }),
          });
          if (!response.ok) throw new Error("Local decision was rejected");
        } catch {
          actions.forEach((item) => { item.disabled = false; });
          document.querySelector("#storage-note").textContent = "Отметка не сохранена. Повторите действие.";
          return;
        }
        document.querySelector("#storage-note").textContent = "Отметка сохранена в локальной истории";
      }
      if (signal && bridge) signal.action = action;
      else if (action === "undo") decisions.delete(key);
      else if (["commented", "skipped"].includes(action)) decisions.set(key, action);
      else return;
      if (!bridge) storeDecisions();
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
