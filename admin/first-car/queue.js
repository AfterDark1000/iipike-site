"use strict";

(() => {
  const commenting = window.firstCarCommenting;
  const panel = document.querySelector("#panel");
  const refreshButton = document.querySelector("#refresh-commenting");
  const storageKey = "hpii:first-car:v1";
  const dzenMirror = /^https:\/\/dzen\.ru\/a\/[A-Za-z0-9_-]{8,100}$/;
  const channelLink = /^https:\/\/dzen\.ru\/(?:[A-Za-z0-9_.-]+|id\/[a-f0-9]{24})$/;
  const httpsLink = /^https:\/\//;
  const clock = new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Asia/Yekaterinburg", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const integer = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
  const minute = 60_000;
  const decisions = readDecisions();
  const authorized = () => document.documentElement.classList.contains("hpii-authorized");
  let watchlist = null;
  let intake = [];
  let snapshot = null;
  let sourceError = false;
  let watchError = false;
  let intakeError = false;
  let loading = false;
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
      return true;
    } catch {
      document.querySelector("#storage-note").textContent = "Отметки хранятся в этой вкладке";
      return false;
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

  function draft(row) {
    if (!row.draft_comment) return "";
    return `<label class="draft-label">Готовая реплика Gemini
      <textarea class="draft-text" readonly rows="3">${escapeText(row.draft_comment)}</textarea></label>`;
  }

  const copyButton = `<button type="button" class="button" data-copy>Скопировать комментарий</button>`;

  function sourceStatus(now) {
    if (sourceError) return `<div class="notice" role="status">Не удалось прочитать очередь Gemini. Нажмите «Обновить».</div>`;
    if (!snapshot) return `<p class="source-note" role="status">Загружаем очередь Gemini…</p>`;
    const stamp = dateLabel(snapshot.updated_at);
    const stale = now - exactTime(snapshot.updated_at) > commenting.staleAfter;
    const failed = snapshot.failed.length ? ` · Сбой лент: ${escapeText(snapshot.failed.join(", "))}` : "";
    const generation = snapshot.generator_status === "error" ? " · Ошибка генерации Gemini" : "";
    const detail = `Снимок Gemini · ${stamp}${failed}${generation}`;
    return stale ? `<div class="notice" role="status"><strong>Очередь не обновлялась более 90 минут</strong><span>${detail}</span></div>` :
      `<p class="source-note" role="status">${detail}</p>`;
  }

  async function refresh() {
    if (!authorized() || loading) return;
    loading = true;
    refreshButton.disabled = true;
    const watch = fetch("/admin/first-car/watchlist.json", {
      cache: "no-store", signal: AbortSignal.timeout(15_000),
    })
      .then((response) => {
        if (!response.ok) throw Error("Watchlist unavailable");
        return response.json();
      }).then((data) => {
        if (!Array.isArray(data?.channels) || !Array.isArray(data?.articles)) throw Error("Invalid watchlist");
        return data;
      });
    const [data, research, links] = await Promise.allSettled([commenting.read(), watch, commenting.readIntake()]);
    loading = false;
    refreshButton.disabled = false;
    if (!authorized()) return;
    sourceError = data.status !== "fulfilled";
    watchError = research.status !== "fulfilled";
    intakeError = links.status !== "fulfilled";
    snapshot = sourceError ? null : data.value;
    watchlist = watchError ? null : research.value;
    intake = intakeError ? [] : links.value;
    render();
  }

  function candidateRow(row, age) {
    const native = row.kind === "dzen";
    const manual = row.source === "manual_dzen";
    const saved = decisions.get(row.key);
    const mark = (action, name) => `<button type="button" class="button" data-candidate="${escapeText(row.key)}" data-decision="${action}">${name}</button>`;
    const search = `https://dzen.ru/search?query=${encodeURIComponent(`${row.title} ${row.source_name}`)}`;
    return `<article class="row candidate">
      <div class="row-top"><span class="muted">${escapeText(row.source_name)}</span><div class="tags">
        ${status(manual ? "Ссылка подтверждена вручную" : native ? "Разовый замер Дзена" : "Есть реплика Gemini")}
        ${native ? status("Сверить обсуждение", "stale") : !row.dzen_url ? status("Без прямой ссылки на Дзен", "stale") : ""}</div></div>
      <h3>${escapeText(row.title)}</h3>
      <dl>${field(native ? "Опубликовано в Дзене" : "Опубликовано у издателя", dateLabel(row.dzen_published_at ?? row.publisher_published_at))}
        ${field("Возраст статьи", ageLabel(age))}
        ${native ? field("Комментарии в замере", known(row.comments)) + field("Просмотры в замере", known(row.views)) : ""}</dl>
      <p class="details">${manual ? `Добавлено ${dateLabel(row.first_seen_at)}.` :
        native ? `Счётчики на ${dateLabel(row.observed_at)}.` : escapeText(row.reason)}</p>
      ${row.angle ? `<p class="details">${escapeText(row.angle)}</p>` : ""}
      ${draft(row)}
      <div class="actions">
        ${row.dzen_url ? link(row.dzen_url, "Открыть в Дзене", dzenMirror, "button primary") : link(search, "Найти в Дзене", httpsLink, "button primary")}
        ${row.source_url ? link(row.source_url, "Оригинал", httpsLink, "button") : ""}
        ${row.draft_comment ? copyButton : ""}
        ${saved ? status(saved === "commented" ? "Прокомментировано" : "Пропущено") + mark("undo", "Вернуть") :
          mark("commented", "Прокомментировано") + mark("skipped", "Пропустить")}
      </div></article>`;
  }

  function channelPanel() {
    if (watchError) return `<p class="section-empty">Не удалось прочитать список каналов.</p>`;
    if (!watchlist) return `<p class="section-empty">Загружаем список каналов…</p>`;
    return `<header class="panel-head"><h2>Приоритетные каналы</h2>
      <p>Ручной просмотр. Замер от ${dateLabel(watchlist.observed_at)}.</p></header>` + watchlist.channels.map((channel) => `
      <article class="row"><h3>${link(channel.url, channel.name, channelLink)}</h3>
      <p class="details">${escapeText(channel.reason)}</p></article>`).join("");
  }

  function grouped(entries) {
    const ranges = [[0, 120, "0–2 ч · первый приоритет"], [120, 480, "2–8 ч · основная очередь"],
      [480, 1441, "8–24 ч · поздние возможности"]];
    const tier = ({ row }) => row.comments == null ? 2 : Number(row.comments > 3);
    const groups = ranges.map(([start, end, label]) => {
      const group = entries.filter(({ age }) => age !== null && start <= age && age < end)
        .sort((a, b) => tier(a) - tier(b) || a.age - b.age);
      return group.length ? `<h4 class="age-group">${label}</h4>` + group.map(({ row, age }) => candidateRow(row, age)).join("") : "";
    }).join("");
    const undated = entries.filter(({ age }) => age === null);
    return groups + (undated.length ? '<h4 class="age-group">Точное время публикации неизвестно</h4>' +
      undated.map(({ row, age }) => candidateRow(row, age)).join("") : "");
  }

  function render() {
    if (!authorized()) return;
    const now = Date.now();
    const native = [...commenting.intakeCandidates(intake, now), ...commenting.nativeCandidates(watchlist, now)];
    const rows = new Map(native.map((row) => [row.key, row]));
    for (const row of snapshot?.candidates ?? []) {
      const previous = rows.get(row.key);
      // Preserve the Dzen timestamp and counts when Gemini points to this exact article.
      rows.set(row.key, previous ? { ...previous, draft_comment: row.draft_comment, source_url: row.source_url } : row);
    }
    const entries = [...rows.values()].map((row) => ({ row,
      age: minutesBetween(exactTime(row.dzen_published_at ?? row.publisher_published_at), now),
    })).filter(({ row, age }) => age === null ? row.source === "manual_dzen" : age <= 1440)
      .sort((a, b) => (a.age ?? 1441) - (b.age ?? 1441));
    const sections = ["Статьи с прямой ссылкой на Дзен", "Реплики к статьям издателей"];
    const open = entries.filter(({ row }) => !decisions.has(row.key));
    const handled = entries.filter(({ row }) => decisions.has(row.key));
    document.querySelector("#queue-count").textContent = open.length;
    document.querySelectorAll(".navigation [data-view]").forEach((button) => {
      if (button.dataset.view === view) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    const pane = (index) => {
      const picked = open.filter(({ row }) => (row.kind === "dzen") === (index === 0));
      const empty = index === 0 ? "Нет подтверждённых ссылок на статьи за последние 24 часа." : "Готовых реплик за последние 24 часа нет.";
      return `<header class="panel-head ${index > 0 ? "candidate-head" : ""}"><h2>${sections[index]}</h2></header>
        ${index > 0 ? sourceStatus(now) : watchError ? `<p class="source-note">Замер каналов недоступен.</p>` : ""}
        ${index === 0 && intakeError ? `<p class="source-note">Не удалось прочитать добавленные ссылки Дзена.</p>` : ""}
        ${picked.length ? grouped(picked) : `<p class="section-empty">${empty}</p>`}`;
    };
    panel.innerHTML = view === "channels" ? channelPanel() : pane(0) + pane(1) + (handled.length ?
      `<details class="handled"><summary>Отмеченные кандидаты · ${handled.length}</summary>
      ${handled.map(({ row, age }) => candidateRow(row, age)).join("")}</details>` : "");
  }

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button || !authorized()) return;
    if (button === refreshButton) void refresh();
    else if (button.dataset.view) {
      view = button.dataset.view;
      render();
    } else if (button.hasAttribute("data-copy")) {
      const text = button.closest("article").querySelector(".draft-text");
      try {
        await navigator.clipboard.writeText(text.value);
        button.textContent = "Скопировано";
      } catch {
        text.focus();
        text.select();
        document.querySelector("#announcement").textContent = "Текст выделен. Скопируйте его вручную.";
      }
    } else if (button.dataset.candidate) {
      const { candidate, decision } = button.dataset;
      if (decision === "undo") decisions.delete(candidate);
      else if (decision === "commented" || decision === "skipped") decisions.set(candidate, decision);
      else return;
      storeDecisions();
      render();
      document.querySelector('.navigation [data-view="queue"]').focus();
    }
  });

  window.addEventListener("hpii-admin-authorized", () => { render(); void refresh(); });
  window.addEventListener("hpii-admin-signout", () => {
    snapshot = null;
    watchlist = null;
    intake = [];
    panel.replaceChildren();
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) void refresh(); });
  window.setInterval(() => { if (!document.hidden) void refresh(); }, 5 * minute);
  if (authorized()) { render(); void refresh(); }
})();
