import {buildRows, counts, selectRows, STATUS_LABELS, DECISION_LABELS}
  from "/admin/pool/pool-data.mjs";

const ROOT = "https://raw.githubusercontent.com/AfterDark1000/iipike-site/main/data/";
const GITHUB = "https://github.com/AfterDark1000/iipike-site";
const PAGE_SIZE = 40;
const state = {rows: null, view: "active", search: "", sort: "priority", shown: PAGE_SIZE,
  loadedAt: null, busy: false};
const byId = id => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function append(parent, node) {parent.appendChild(node); return node;}
function safeHttps(raw) {
  try {const url = new URL(raw);return url.protocol === "https:" ? url.href : null;}
  catch (_) {return null;}
}
function dateLabel(raw) {
  const stamp = Date.parse(raw);
  if (!Number.isFinite(stamp)) return "";
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Asia/Yekaterinburg",
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit"
  }).format(stamp);
}
function routeLabel(row) {
  if (row.decision) return DECISION_LABELS[row.decision] || row.decision;
  return "Не распределена";
}
function tag(parent, text, className = "") {
  return append(parent, el("span", "tag " + className, text));
}
function oneCard(row) {
  const card = el("article", "item");
  const content = append(card, el("div"));
  const top = append(content, el("div", "item-top"));
  append(top, el("span", "number", "#" + row.sequence));
  tag(top, STATUS_LABELS[row.status], row.status === "in_review" ? "work" :
    row.status === "approved" ? "ok" :
    row.status === "rejected" ? "closed" : "");
  tag(top, routeLabel(row), row.category);
  if (row.effective_high && row.category !== "hot") tag(top, "Высокий приоритет", "hot");
  append(content, el("h3", null, row.title));
  if (row.summary) append(content, el("p", "summary", row.summary));
  const more = append(content, el("details"));
  append(more, el("summary", null, "Подробности и ID"));
  const details = append(more, el("div", "details-content"));
  const info = [
    "ID новости: " + row.id,
    "Статус: " + STATUS_LABELS[row.status],
    "Решение сортировщика: " + routeLabel(row),
    "Направление: " + (row.lane === "long" ? "Полная статья" :
      row.lane === "short" ? "Короткая новость" :
      row.lane === "hold" ? "Отложено / отдельный разбор" : "Не задано")
  ];
  if (row.article_id) info.push("ID статьи: " + row.article_id);
  if (row.group) info.push("Группа: " + row.group);
  if (row.added_at) info.push("Добавлено (Усть-Катав): " + dateLabel(row.added_at));
  if (row.origin) info.push("Откуда: " + row.origin);
  info.forEach(t => append(details, el("div", "detail-line", t)));
  if (row.note) append(details, el("p", "detail-line", "Редакторская пометка:\n" + row.note));
  const actions = append(card, el("div", "actions"));
  const source = safeHttps(row.source_url);
  if (source) {
    const link = append(actions, el("a", null, "Первоисточник ↗"));
    link.href = source;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }
  return card;
}
function render() {
  if (!state.rows) return;
  const n = counts(state.rows);
  for (const key of ["all","queued","in_review","approved","rejected"]) {
    byId("count-" + key).textContent = String(n[key]);
  }
  for (const [view, value] of Object.entries({
    active: n.active, hot: n.hot, full: n.full,
    short: n.short, hold: n.hold, work: n.in_review,
    history: n.approved + n.rejected
  })) {
    byId("view-" + view).textContent = String(value);
  }
  document.querySelectorAll("[data-view]").forEach(button => {
    button.setAttribute("aria-pressed", button.dataset.view === state.view ? "true" : "false");
  });
  const list = byId("items");
  list.replaceChildren();
  const selected = selectRows(state.rows, state);
  const visible = selected.slice(0, state.shown);
  const label = selected.length.toLocaleString("ru-RU") + " записей";
  byId("result-line").textContent = "Найдено: " + label + " · показано " + visible.length +
    ". Сортировка — для просмотра; реальный статус определяют данные GitHub.";
  if (!selected.length) {
    append(list, el("div", "empty", state.search ?
      "По запросу ничего не нашлось. Попробуй другой номер или слово." :
      "В этом разделе сейчас нет новостей."));
  } else {
    const fragment = document.createDocumentFragment();
    visible.forEach(row => append(fragment, oneCard(row)));
    list.append(fragment);
  }
  const more = byId("more");
  more.hidden = visible.length >= selected.length;
  more.textContent = "Показать ещё " + Math.min(PAGE_SIZE, selected.length - visible.length);
}
async function fetchJson(name) {
  const url = ROOT + name + "?v=" + Date.now();
  const reply = await fetch(url, {cache: "no-store"});
  if (!reply.ok) throw new Error(name + ": HTTP " + reply.status);
  return reply.json();
}
async function refresh() {
  if (state.busy) return;
  state.busy = true;
  const button = byId("refresh");
  button.disabled = true;
  byId("updated").textContent = "Получаю актуальный пул и маршруты из GitHub…";
  try {
    const [pool, routing] = await Promise.all([
      fetchJson("site_news_pool.json"), fetchJson("editorial_routing.json")
    ]);
    const rows = buildRows(pool, routing);
    state.rows = rows;
    state.loadedAt = new Date();
    state.shown = PAGE_SIZE;
    byId("updated").textContent = "GitHub · main · загружено " +
      dateLabel(state.loadedAt.toISOString()) + " (Усть-Катав)";
    render();
  } catch (error) {
    byId("updated").textContent = "Ошибка загрузки: " + error.message +
      (state.rows ? ". Показаны прежние данные." : "");
    if (!state.rows) {
      byId("result-line").textContent = "Пул не загружен";
      byId("items").replaceChildren(el("div", "error",
        "Не удалось прочитать GitHub. Нажми «Обновить». Данные не изменены."));
    }
  } finally {
    state.busy = false;
    button.disabled = false;
  }
}
byId("refresh").addEventListener("click", refresh);
byId("views").addEventListener("click", event => {
  const button = event.target.closest("button[data-view]");
  if (!button || !byId("views").contains(button)) return;
  state.view = button.dataset.view;
  state.shown = PAGE_SIZE;
  render();
});
byId("search").addEventListener("input", event => {
  state.search = event.target.value;
  state.shown = PAGE_SIZE;
  render();
});
byId("sort").addEventListener("change", event => {
  state.sort = event.target.value;
  state.shown = PAGE_SIZE;
  render();
});
byId("more").addEventListener("click", () => {
  state.shown += PAGE_SIZE;
  render();
});
window.addEventListener("hpii-admin-authorized", refresh);
if (document.documentElement.classList.contains("hpii-authorized")) refresh();
