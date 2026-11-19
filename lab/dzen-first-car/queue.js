"use strict";

(() => {
  const data = window.firstCarSnapshots;
  const panel = document.querySelector("#panel");
  const storageKey = "dzen-first-car-v1";
  const directArticle = /^https:\/\/dzen\.ru\/a\/[A-Za-z0-9_-]{16}$/;
  const dzenMirror = /^https:\/\/dzen\.ru\/a\/[A-Za-z0-9_-]{8,100}$/;
  const httpsLink = /^https:\/\//;
  const channelLink = /^https:\/\/dzen\.ru\/(?:[A-Za-z0-9_.-]+|id\/[a-f0-9]{24})$/;
  const guruLink = /^https:\/\/dzen\.guru\/channels\/[A-Za-z0-9_.-]+$/;
  const clock = new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Asia/Yekaterinburg", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const integer = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
  const percent = new Intl.NumberFormat("ru-RU", { style: "percent", maximumFractionDigits: 1 });
  const minute = 60_000;
  const freshnessLimit = 15 * minute;
  const windowHours = data.window_hours ?? 24;
  const windowMinutes = windowHours * 60;
  const signalWindow = 60 * minute;
  const signals = data.signals ?? [];
  const candidates = data.candidates ?? [];
  const decisions = readDecisions();
  if (data.bridge) {
    for (const key of decisions.keys()) if (key.startsWith("queue|")) decisions.delete(key);
    for (const [url, action] of Object.entries(data.decisions)) decisions.set(`queue|${url}`, action);
    document.querySelector("#storage-note").textContent = "Отметки кандидатов хранятся в браузере";
  }
  if (data.replay) {
    document.querySelector(".local").textContent = "Демо · тестовый прогон";
  } else if (data.archive_mode) {
    document.querySelector(".local").textContent = "Архивный просмотр";
  }
  document.querySelector("#window-hours").textContent = windowHours;
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
        && Number.isInteger(article.comments) && article.comments >= 0 && article.comments <= 15
        && firstSeen !== null && snapshot !== null && firstSeen <= snapshot
        && now >= snapshot && now - snapshot <= freshnessLimit
        && seenAge !== null && seenAge <= windowMinutes && currentAge !== null && currentAge <= windowMinutes;
    });
  }

  function draft(row) {
    if (!row.draft_comment) return "";
    return `<label class="draft-label">Готовая реплика Gemini
      <textarea class="draft-text" readonly rows="3">${escapeText(row.draft_comment)}</textarea></label>`;
  }

  const copyButton = `<button type="button" class="button" data-copy>Скопировать комментарий</button>`;

  function discussionChange(row) {
    if (!row.comment_change) return "";
    const change = row.comment_change;
    const delta = change.delta > 0 ? `+${change.delta}` : String(change.delta);
    return `<p class="details">Изменение числа комментариев: ${delta} · ${dateLabel(change.from_at)} → ${dateLabel(change.to_at)}</p>`;
  }

  function grouped(rows, now, renderRow) {
    const groups = [[], [], [], []];
    for (const row of rows) {
      const published = row.dzen_published_at ?? row.publisher_published_at ?? row.published_at;
      const age = minutesBetween(exactTime(published), now);
      if (age === null || age > windowMinutes) continue;
      const band = age < 120 ? 0 : age < 480 ? 1 : age <= 1440 ? 2 : 3;
      const tier = row.comments == null ? 2 : Number(row.comments > 3);
      groups[band].push({ row, tier, age });
    }
    const labels = ["0–2 ч · первый приоритет", "2–8 ч · основная очередь", "8–24 ч · поздние возможности",
      `24–${windowHours} ч · резерв`];
    return groups.map((group, index) => group.length ? `<h4 class="age-group">${labels[index]}</h4>` +
      group.sort((a, b) => a.tier - b.tier || a.age - b.age).map(({ row, age }) => renderRow(row, age)).join("") : "").join("");
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
            data.replay ? "Тестовая карточка" : data.archive_mode ? "Подтверждено в снимке" : "Подтверждено", "observed")}</div>
        <h3>${data.replay && !demo ? escapeText(article.title) : link(article.url, article.title, directArticle)}</h3>
        <dl>
          ${field("Опубликовано", dateLabel(article.published_at))}
          ${field("Возраст при находке", ageLabel(age))}
          ${field("Комментарии в снимке", known(article.comments))}
          ${field("Просмотры в снимке", known(article.views))}
        </dl>
        ${article.publisher_published_at ? `<p class="details">У издателя · ${dateLabel(article.publisher_published_at)}</p>` : ""}
        <p class="details"><strong>История канала</strong> · медиана ${known(channel.median_views)} по ${known(channel.views_known)} ст.
          · с обсуждениями ${known(channel.discussion_rate, percent)}</p>
        <p class="details">${demo ? "Аудитория не подтверждена. Опубликовано за пределами окна." :
          article.comments <= 3 ? "Обсуждение открыто · первый эшелон." : "Обсуждение открыто · второй эшелон."}</p>
        ${discussionChange(article)}${draft(article)}
        <p class="details">${data.replay && !demo ? "Тестовый снимок" :
          escapeText(article.source || "Снимок Дзена")} · ${dateLabel(article.observed_at)}
          ${demo ? " · определение просмотров не сверено" : ` · впервые ${dateLabel(article.first_seen_at)}`}</p>
        <div class="actions">${data.replay && !demo ? "" : link(article.url, "Открыть", directArticle, "button primary")}
          ${article.source_url ? link(article.source_url, "Оригинал", httpsLink, "button") : ""}
          ${article.draft_comment ? copyButton : ""}${decisionButtons}</div>
      </article>`;
  }

  function candidateRow(row, age) {
    const native = row.kind === "dzen";
    const synthetic = row.source_policy === "fixture";
    const stored = decisions.get(`candidate|${row.key}`);
    const mark = (action, name) => `<button type="button" class="button" data-candidate="${escapeText(row.key)}" data-decision="${action}">${name}</button>`;
    const search = `https://dzen.ru/search?query=${encodeURIComponent(`${row.title} ${row.source_name}`)}`;
    const history = row.history;
    const date = native ? row.dzen_published_at : row.publisher_published_at;
    return `<article class="row candidate">
      <div class="row-top"><span class="muted">${escapeText(row.source_name)}</span>
        <div class="tags">${status(synthetic ? "Тестовая карточка" : row.confidence === "publisher_only" ? "Есть реплика Gemini" : "Частично подтверждено")}
        ${!row.dzen_url ? status("Без прямой ссылки на Дзен", "stale") : ""}
        ${row.historical ? status("Архивные счётчики", "stale") : ""}</div></div>
      <h3>${escapeText(row.title)}</h3>
      <dl>
        ${field(native ? "Опубликовано в Дзене" : "Опубликовано у издателя", dateLabel(date))}
        ${field("Возраст в окне", ageLabel(age))}
        ${native ? field("Комментарии в снимке", known(row.comments)) + field("Просмотры в снимке", known(row.views)) : ""}
      </dl>
      ${native && row.publisher_published_at ? `<p class="details">У издателя · ${dateLabel(row.publisher_published_at)}</p>` : ""}
      <p class="details">${escapeText(row.reason)} ${native ? `Снимок Дзена · ${dateLabel(row.observed_at)}. ${
        row.comments_open === true ? "Обсуждение открыто в снимке." : "Статус обсуждения неизвестен."}` : ""}</p>
      ${native && history?.median_views != null ? `<p class="details"><strong>Общий поток</strong> · медиана ${known(history.median_views)} просмотров по ${known(history.views_known)} ст. возраста ${history.age_hours.join("–")} ч · ${known(history.discussed)} с обсуждениями.</p>` : ""}
      ${discussionChange(row)}${draft(row)}
      <div class="actions">
        ${synthetic ? "" : row.dzen_url ? link(row.dzen_url, "Открыть в Дзене", dzenMirror, "button primary") : link(search, "Найти в Дзене", httpsLink, "button primary")}
        ${row.source_url ? link(row.source_url, "Оригинал", httpsLink, "button") : ""}
        ${row.draft_comment ? copyButton : ""}
        ${stored ? status(stored === "commented" ? "Прокомментировано" : "Пропущено") + mark("undo", "Вернуть") :
          mark("commented", "Прокомментировано") + mark("skipped", "Пропустить")}
      </div>
    </article>`;
  }

  function queuePanel(now, entries, pending, available, handledCandidates) {
    const latest = exactTime(data.latest_observed_at) ??
      Math.max(...data.articles.map((item) => exactTime(item.observed_at) ?? -Infinity));
    const stale = Number.isFinite(latest) && now - latest > freshnessLimit;
    const source = stale ? `<div class="notice"><strong>Источник устарел</strong>
      <span>Последний снимок ${clock.format(latest)}.</span></div>` : "";
    const handled = entries.filter((article) => decisions.has(`queue|${article.url}`));
    const archive = data.archive_mode ? `<div class="notice"><strong>Просмотр сохранённых данных</strong>
      <span>Окно на ${dateLabel(data.as_of)}. Счётчики с тех пор могли измениться.</span></div>` : "";
    return `${archive}<header class="panel-head"><h2>Проверенные возможности</h2><p>Ожидают отметки · ${pending.length}</p></header>
      ${source}${pending.length ? grouped(pending, now, (article) => articleRow(article)) : `<p class="section-empty">Проверенных возможностей в этом окне нет.</p>`}
      ${handled.length ? `<details class="handled"><summary>Отмеченные · ${handled.length}</summary>
        ${handled.map((article) => articleRow(article)).join("")}</details>` : ""}
      <header class="panel-head candidate-head"><h2>Кандидаты на просмотр</h2><p>Ожидают ручной оценки · ${available.length}</p></header>
      ${available.length ? grouped(available, now, candidateRow) : `<p class="section-empty">Кандидатов в этом окне нет.</p>`}
      ${handledCandidates.length ? `<details class="handled"><summary>Отмеченные кандидаты · ${handledCandidates.length}</summary>
        ${grouped(handledCandidates, now, candidateRow)}</details>` : ""}`;
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
    const now = data.replay || data.archive_mode ? exactTime(data.as_of) : Date.now();
    const eligible = queueEntries(now);
    const pending = eligible.filter((article) => !decisions.has(`queue|${article.url}`));
    const currentCandidates = candidates.filter((row) => {
      const age = minutesBetween(exactTime(row.dzen_published_at ?? row.publisher_published_at), now);
      return age !== null && age <= windowMinutes;
    });
    const openCandidates = currentCandidates.filter((row) => !decisions.has(`candidate|${row.key}`));
    const currentSignals = signals.filter((signal) => {
      const seen = exactTime(signal.detected_at);
      return signal.verified === false && directArticle.test(signal.url) && seen !== null
        && seen <= now && now - seen <= signalWindow;
    });
    const pendingSignals = currentSignals.filter((signal) => !signal.action);
    document.querySelector("#queue-count").textContent = pending.length + openCandidates.length;
    document.querySelector("#signal-count").textContent = pendingSignals.length;
    document.querySelector("#channel-count").textContent = data.channels.length;
    document.querySelectorAll(".navigation [data-view]").forEach((button) => {
      if (button.dataset.view === view) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    panel.innerHTML = view === "queue" ? queuePanel(now, eligible, pending, openCandidates,
      currentCandidates.filter((row) => decisions.has(`candidate|${row.key}`))) :
      view === "signals" ? signalPanel(pendingSignals, currentSignals.filter((signal) => signal.action)) :
      view === "channels" ? channelPanel() : demoPanel();
    clearTimeout(signalTimer);
    if (view === "signals" && !data.replay && !data.archive_mode && currentSignals.length) {
      const oldest = exactTime(currentSignals[currentSignals.length - 1].detected_at);
      signalTimer = setTimeout(render, oldest + signalWindow - now + 1);
    }
  }

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.hasAttribute("data-copy")) {
      const text = button.closest("article").querySelector(".draft-text");
      try {
        await navigator.clipboard.writeText(text.value);
        document.querySelector("#announcement").textContent = "Комментарий скопирован";
        button.textContent = "Скопировано";
      } catch {
        text.focus();
        text.select();
        document.querySelector("#announcement").textContent = "Текст выделен. Скопируйте его вручную.";
      }
      return;
    }
    if (button.dataset.candidate) {
      const key = `candidate|${button.dataset.candidate}`;
      const action = button.dataset.decision;
      if (action === "undo") decisions.delete(key);
      else if (action === "commented" || action === "skipped") decisions.set(key, action);
      storeDecisions();
      document.querySelector("#announcement").textContent = "Отметка кандидата сохранена локально";
      render();
      document.querySelector('.navigation [data-view="queue"]').focus();
      return;
    }
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
