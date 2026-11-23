// Read-only view-model for the public HPII raw news pool.
// It never writes back to the editorial pool or routing files.
const statuses = new Set(["queued", "in_review", "approved", "rejected"]);
const laneWeights = {hot: 0, full: 1, short: 2, hold: 3, other: 4};
const activeStatuses = new Set(["queued", "in_review"]);

export const STATUS_LABELS = Object.freeze({
  queued: "Ожидает", in_review: "В работе",
  approved: "Согласована", rejected: "Закрыта"
});
export const DECISION_LABELS = Object.freeze({
  hot: "Горячая", full: "Полная статья", short: "Короткая",
  linked_primary: "Серия · основная", linked_secondary: "Серия · связанная",
  defer: "Отложена", manual: "Ручной разбор",
  reject_after_verification: "Закрыть после проверки"
});

export function buildRows(pool, routing) {
  if (!pool || pool.schema_version !== 1 || !Array.isArray(pool.items)) {
    throw new Error("Неверный формат site_news_pool.json");
  }
  if (!routing || routing.schema_version !== 1 || !Array.isArray(routing.items)) {
    throw new Error("Неверный формат editorial_routing.json");
  }
  const routeById = new Map();
  for (const route of routing.items) {
    if (!route || typeof route.pool_id !== "string" || !Number.isInteger(route.sequence)) {
      throw new Error("Некорректная запись маршрутизации");
    }
    if (routeById.has(route.pool_id)) throw new Error("Повтор маршрута " + route.pool_id);
    routeById.set(route.pool_id, route);
  }
  const seen = new Set();
  return pool.items.map(item => {
    if (!item || !Number.isInteger(item.sequence) || item.sequence <= 0 ||
        typeof item.id !== "string" || !statuses.has(item.status) ||
        typeof item.title !== "string") {
      throw new Error("Некорректная запись в пуле");
    }
    if (seen.has(item.id)) throw new Error("Повтор новости " + item.id);
    seen.add(item.id);
    const route = routeById.get(item.id);
    if (route && route.sequence !== item.sequence) {
      throw new Error("Несоответствие номера и маршрута для #" + item.sequence);
    }
    const lane = route?.lane || "other";
    const decision = route?.decision || "";
    const category = decision === "hot" ? "hot" :
      lane === "long" ? "full" :
      lane === "short" ? "short" :
      lane === "hold" ? "hold" : "other";
    return {
      id: item.id, sequence: item.sequence, title: item.title,
      summary: item.summary || "", note: item.note || "",
      source_url: item.source_url || "", article_id: item.article_id || "",
      origin: item.origin || "", added_at: item.added_at || "",
      priority: item.priority || "normal", status: item.status,
      lane, decision, category, group: route?.group || "",
      active: activeStatuses.has(item.status),
      // Use the sorter decision as the source of truth for hot news.
      effective_high: item.priority === "high" || decision === "hot"
    };
  });
}

export function counts(rows) {
  const n = {all: rows.length, queued: 0, in_review: 0, approved: 0, rejected: 0,
    active: 0, hot: 0, full: 0, short: 0, hold: 0};
  for (const row of rows) {
    n[row.status]++;
    if (row.active) {
      n.active++;
      if (Object.hasOwn(n, row.category)) n[row.category]++;
    }
  }
  return n;
}

export function selectRows(rows, {view = "active", search = "", sort = "priority"} = {}) {
  const q = String(search).trim().toLocaleLowerCase("ru-RU").replace(/^#/, "");
  const filtered = rows.filter(r => {
    const inView = view === "all" || (view === "history"
      ? !r.active
      : view === "work" ? r.status === "in_review"
      : view === "active" ? r.active
      : r.active && r.category === view);
    if (!inView) return false;
    if (!q) return true;
    return String(r.sequence).includes(q) ||
      [r.id, r.title, r.summary, r.article_id].some(x =>
        String(x).toLocaleLowerCase("ru-RU").includes(q));
  });
  if (sort === "new") filtered.sort((a, b) => b.sequence - a.sequence);
  else if (sort === "fifo") filtered.sort((a, b) => a.sequence - b.sequence);
  else filtered.sort((a, b) =>
    (laneWeights[a.category] ?? 9) - (laneWeights[b.category] ?? 9) ||
    a.sequence - b.sequence);
  return filtered;
}
