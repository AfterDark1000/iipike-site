(function () {
  "use strict";
  const KEY = "hpii:commenting:v1";
  const DATA_URL = "https://raw.githubusercontent.com/AfterDark1000/iipike-site/commenting-data/commenting/queue.json";
  const ID = /^[a-f0-9]{24}$/;
  function directDzen(url) { return typeof url === "string" && /^https:\/\/dzen\.ru\/a\/[A-Za-z0-9_-]{8,100}$/.test(url); }
  function safeURL(url) { try { const u = new URL(url); return u.protocol === "https:" && !u.username && !u.password ? u.href : null; } catch (_) { return null; } }
  function validRecords(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw Error("Некорректный файл отметок");
    const clean = {};
    Object.keys(value).slice(0, 2000).forEach(function (id) {
      const row = value[id];
      if (!ID.test(id) || !row || typeof row !== "object") return;
      const next = {};
      if (["posted", "skipped"].includes(row.status)) next.status = row.status;
      if (typeof row.text === "string" && row.text.length <= 2500) next.text = row.text;
      if (directDzen(row.dzen_url)) next.dzen_url = row.dzen_url;
      if (Object.keys(next).length) clean[id] = next;
    });
    return clean;
  }
  function fresh(row, now, hours) { const t = Date.parse(row.published_at); return Number.isFinite(t) && now >= t && now - t <= hours * 3600000; }
  function selectRows(queue, records, filter, source, now) {
    return queue.items.filter(function (row) {
      if (source !== "all" && row.source_id !== source) return false;
      const local = records[row.id] || {};
      if (filter === "history") return !!local.status;
      if (local.status || !fresh(row, now, queue.max_age_hours)) return false;
      if (filter === "pending") return row.status !== "draft_ready";
      if (row.status !== "draft_ready" || !row.comment) return false;
      return filter !== "linked" || directDzen(local.dzen_url || row.dzen_url);
    });
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { validRecords, selectRows, directDzen, fresh, safeURL };
  if (typeof document === "undefined") return;
  let queue = null, loadError = "", storageError = false, records = {}, loading = false, refreshedAt = null;
  try { records = validRecords(JSON.parse(localStorage.getItem(KEY) || "{}")); } catch (_) { storageError = true; }
  const $ = id => document.getElementById(id);
  function node(tag, text, cls) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; }
  function add(parent, tag, text, cls) { const n = node(tag, text, cls); parent.appendChild(n); return n; }
  function button(parent, text, fn, cls) { const b = add(parent, "button", text, cls); b.type = "button"; b.addEventListener("click", fn); return b; }
  function anchor(parent, text, url, cls) { const safe = safeURL(url); if (!safe) return; const a = add(parent, "a", text, cls); a.href = safe; a.target = "_blank"; a.rel = "noopener noreferrer"; return a; }
  function time(value) { const t = Date.parse(value); return Number.isFinite(t) ? new Date(t).toLocaleString("ru-RU", { timeZone: "Asia/Yekaterinburg", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "дата неизвестна"; }
  function save(id, patch) {
    const next = Object.assign({}, records, { [id]: Object.assign({}, records[id], patch) });
    try { localStorage.setItem(KEY, JSON.stringify(next)); records = next; storageError = false; return true; }
    catch (_) { storageError = true; return false; }
  }
  function messages() {
    $("messages").replaceChildren();
    if (storageError) add($("messages"), "div", "Не удалось сохранить или прочитать отметки браузера. Не закрывай страницу с несохранёнными правками.", "notice error");
    if (loadError) add($("messages"), "div", loadError + (queue ? " Показана предыдущая загруженная очередь." : ""), "notice error");
    if (!queue) return;
    if (Date.now() - Date.parse(queue.updated_at) > 2 * 3600000) add($("messages"), "div", "Очередь не обновлялась больше двух часов. Проверь журнал сборщика; отсутствие карточек не означает отсутствие новостей.", "notice warning");
    const failed = queue.sources.filter(s => s.status !== "ok");
    if (failed.length) add($("messages"), "div", "Не проверены источники: " + failed.map(s => s.name).join(", ") + ". Подробнее — в диагностике ниже.", "notice warning");
    if (!["ok", "idle"].includes(queue.generator.status)) add($("messages"), "div", queue.generator.message || "Генерация недоступна", "notice warning");
  }
  function card(row) {
    const local = records[row.id] || {};
    const article = add($("items"), "article", undefined, "card");
    const meta = add(article, "div", undefined, "meta");
    add(meta, "span", row.source_name + " · опубликовано " + time(row.published_at));
    add(meta, "span", "найдено " + time(row.first_seen_at));
    if (!fresh(row, Date.now(), queue.max_age_hours)) add(meta, "span", "Старая статья", "badge warn");
    const heading = add(article, "h2"); anchor(heading, row.title, row.source_url);
    const url = local.dzen_url || row.dzen_url;
    if (directDzen(url)) add(article, "span", local.dzen_url ? "Ссылка в Дзен добавлена тобой" : "Издание указало зеркало в Дзене", "badge");
    else add(article, "span", "Прямой ссылки в Дзен нет", "badge warn");
    if (local.status) add(article, "span", local.status === "posted" ? "Разместил — твоя отметка" : "Пропущено", "badge");
    let textarea = null, state = null;
    if (row.comment) {
      const label = add(article, "label", "Комментарий · можно поправить", "text-label"); label.htmlFor = "text-" + row.id;
      textarea = add(article, "textarea"); textarea.id = label.htmlFor; textarea.value = local.text !== undefined ? local.text : row.comment; textarea.maxLength = 2500;
      state = add(article, "div", "", "save-state"); state.setAttribute("role", "status");
      textarea.addEventListener("input", function () {
        const ok = save(row.id, { text: textarea.value });
        state.textContent = ok ? "Правка сохранена в этом браузере" : "Правка НЕ сохранена";
        state.className = ok ? "save-state" : "save-state error"; messages();
      });
    } else add(article, "p", row.reason || (row.status === "pending" ? "Ожидает чтения и подготовки комментария" : "Комментарий не подготовлен"), "hint");
    const actions = add(article, "div", undefined, "actions");
    if (textarea) {
      const copy = button(actions, "Скопировать", async function () {
        try { if (!textarea.value.trim()) throw Error("Текст пустой"); await navigator.clipboard.writeText(textarea.value); copy.textContent = "Скопировано ✓"; }
        catch (_) { textarea.focus(); textarea.select(); state.textContent = "Нажми Ctrl+C или выбери «Копировать» в меню выделенного текста"; }
      }, "primary");
    }
    if (directDzen(url)) anchor(actions, "Открыть в Дзене ↗", url, "button");
    else anchor(actions, "Найти в Дзене ↗", "https://dzen.ru/search?query=" + encodeURIComponent(row.title + " " + row.source_name), "button");
    anchor(actions, "Оригинал ↗", row.source_url, "button");
    function mark(status) {
      if (save(row.id, { status: status, ...(textarea ? { text: textarea.value } : {}) })) render();
      else { messages(); if (state) state.textContent = "Отметка НЕ сохранена"; }
    }
    if (local.status) button(actions, "Вернуть", () => mark(null));
    else {
      if (textarea) button(actions, "Разместил", () => mark("posted"));
      button(actions, "Пропустить", () => mark("skipped"));
    }
    const details = add(article, "details"); add(details, "summary", "Заметка к статье и ссылка в Дзен");
    add(details, "p", row.reason || "Комментарий подготовлен по тексту оригинала издания.");
    if (row.generated_at) add(details, "p", "Подготовлено " + time(row.generated_at));
    const group = add(details, "div", undefined, "link-entry");
    const input = add(group, "input"); input.type = "url"; input.placeholder = "https://dzen.ru/a/…"; input.setAttribute("aria-label", "Ссылка на эту статью в Дзене"); input.value = local.dzen_url || "";
    const feedback = add(details, "p", "", "save-state"); feedback.setAttribute("role", "status");
    button(group, "Сохранить ссылку", function () {
      const value = input.value.trim().split("?")[0].split("#")[0];
      if (value && !directDzen(value)) { feedback.textContent = "Нужна прямая ссылка вида https://dzen.ru/a/…"; return; }
      if (save(row.id, { dzen_url: value || null })) render(); else { feedback.textContent = "Ссылка НЕ сохранена"; messages(); }
    }, "small");
  }
  function render() {
    messages();
    $("items").replaceChildren(); $("health").replaceChildren();
    if (!queue) { add($("items"), "p", "Нет загруженной очереди. Попробуй обновить; подробности ошибки показаны выше.", "empty"); return; }
    $("updated").textContent = "Очередь: " + time(queue.updated_at) + " · Усть-Катав · загружена " + time(refreshedAt);
    $("ready").textContent = selectRows(queue, records, "ready", "all", Date.now()).length;
    $("linked").textContent = selectRows(queue, records, "linked", "all", Date.now()).length;
    $("posted").textContent = Object.values(records).filter(r => r.status === "posted").length;
    const rows = selectRows(queue, records, $("filter").value, $("source").value, Date.now());
    rows.forEach(card);
    if (!rows.length) {
      let text = "В этом списке пока нет материалов.";
      if ($("filter").value === "ready") text = "Свежих готовых комментариев пока нет. Проверь список «В работе / ошибки» и диагностику источников.";
      if ($("filter").value === "linked") text = "Прямые ссылки в Дзен пока не получены. Остальные комментарии доступны в списке готовых.";
      add($("items"), "p", text, "empty");
    }
    queue.sources.forEach(function (s) {
      const block = add($("health"), "div", undefined, "health-row");
      add(block, "strong", s.name + " · " + (s.status === "ok" ? "лента прочитана" : "ошибка"));
      add(block, "div", "Проверено " + time(s.checked_at) + (s.status === "ok" ? " · свежих совпадений по теме: " + s.fresh_matches : " · " + (s.error || "источник недоступен")));
      if (s.last_success_at && s.status !== "ok") add(block, "div", "Последняя успешная проверка " + time(s.last_success_at));
    });
    add($("health"), "p", "Генерация: " + queue.generator.message + " · обработано за день: " + queue.usage.attempted, "hint");
  }
  async function refresh() {
    if (loading) return; loading = true; $("refresh").disabled = true;
    try {
      const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
      let response; try { response = await fetch(DATA_URL + "?v=" + Date.now(), { cache: "no-store", signal: controller.signal }); } finally { clearTimeout(timer); }
      if (!response.ok) throw Error(response.status === 404 ? "Первая очередь ещё не сохранена — проверь журнал обновлений." : "Ошибка загрузки: HTTP " + response.status);
      const next = await response.json();
      if (next.schema_version !== 1 || !Array.isArray(next.items) || !Array.isArray(next.sources) || !next.generator || !next.usage || !Number.isFinite(Date.parse(next.updated_at)) || !Number.isFinite(next.max_age_hours)) throw Error("Формат очереди не распознан");
      if (next.items.some(r => !ID.test(r.id) || typeof r.title !== "string" || typeof r.comment !== "string" || !safeURL(r.source_url))) throw Error("В очереди некорректная карточка");
      queue = next; refreshedAt = new Date().toISOString(); loadError = "";
      const selected = $("source").value; $("source").replaceChildren(); const all = add($("source"), "option", "Все издания"); all.value = "all";
      queue.sources.forEach(s => { const opt = add($("source"), "option", s.name); opt.value = s.id; });
      $("source").value = Array.from($("source").options).some(o => o.value === selected) ? selected : "all";
    } catch (e) { loadError = e.name === "AbortError" ? "Истекло время загрузки очереди." : e.message; if (!queue) $("updated").textContent = "Очередь недоступна"; }
    finally { loading = false; $("refresh").disabled = false; render(); }
  }
  $("filter").addEventListener("change", render); $("source").addEventListener("change", render); $("refresh").addEventListener("click", refresh);
  $("export").addEventListener("click", function () {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ schema_version: 1, records: records }, null, 2)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = "hpii-commenting-marks.json"; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  $("import").addEventListener("change", async function () {
    try {
      const file = $("import").files[0]; if (!file) return; if (file.size > 2000000) throw Error("Файл слишком большой");
      const data = JSON.parse(await file.text()); if (data.schema_version !== 1) throw Error("Неизвестный формат отметок");
      const imported = validRecords(data.records), next = Object.assign({}, imported, records);
      localStorage.setItem(KEY, JSON.stringify(next)); records = next; storageError = false; render();
    } catch (e) { alert("Не удалось восстановить отметки: " + e.message); } finally { $("import").value = ""; }
  });
  window.addEventListener("storage", e => { if (e.key === KEY) { try { records = validRecords(JSON.parse(e.newValue || "{}")); render(); } catch (_) { storageError = true; messages(); } } });
  refresh();
})();
