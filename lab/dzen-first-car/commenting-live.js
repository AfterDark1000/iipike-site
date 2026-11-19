"use strict";

const firstCarCommenting = (() => {
  const SOURCE = "https://raw.githubusercontent.com/AfterDark1000/iipike-site/commenting-data/commenting/queue.json";
  const HOUR = 3_600_000;
  const DIRECT = /^https:\/\/dzen\.ru\/a\/[A-Za-z0-9_-]{8,100}$/;
  const ZONED = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

  function timestamp(value) {
    return typeof value === "string" && ZONED.test(value) ? Date.parse(value) : NaN;
  }

  function normalize(queue, now) {
    const updated = timestamp(queue?.updated_at);
    if (queue?.schema_version !== 1 || !Array.isArray(queue.sources) || !Array.isArray(queue.items)
        || !Number.isFinite(updated) || updated > now) throw new Error("Некорректный снимок очереди Gemini");

    const sources = new Map(queue.sources.filter((source) => typeof source?.id === "string")
      .map((source) => [source.id, source]));
    const candidates = new Map();
    for (const row of queue.items) {
      const source = sources.get(row?.source_id);
      const age = now - timestamp(row?.published_at);
      if (!source || row.status !== "draft_ready" || !(age >= 0 && age <= 24 * HOUR)
          || typeof row.title !== "string" || !row.title.trim()
          || typeof row.comment !== "string" || !row.comment.trim()) continue;

      let original;
      try { original = new URL(row.source_url); } catch { continue; }
      if (original.protocol !== "https:" || original.username || original.password) continue;
      original.hash = "";
      const mirror = DIRECT.test(row.dzen_url) ? row.dzen_url : null;
      const key = mirror || original.href;
      if (candidates.has(key)) continue;
      candidates.set(key, {
        key, kind: "publisher", title: row.title, source_name: String(source.name || source.id),
        source_url: original.href, dzen_url: mirror, observed_at: queue.updated_at,
        publisher_published_at: row.published_at, dzen_published_at: null, comments: null,
        confidence: "publisher_only", draft_comment: row.comment,
        reason: mirror ? "Статья сайта издателя. Время публикации в Дзене и обсуждение не сверены." :
          "Статья сайта издателя. Ссылка на версию Дзена неизвестна.",
      });
    }
    return {
      updated_at: queue.updated_at, candidates: [...candidates.values()],
      failed: [...sources.values()].filter((source) => source.status !== "ok")
        .map((source) => String(source.name || source.id)),
    };
  }

  async function read(fetcher = fetch) {
    const url = new URL(SOURCE);
    url.searchParams.set("t", String(Date.now()));
    const response = await fetcher(url, {
      mode: "cors", cache: "no-store", credentials: "omit", signal: AbortSignal.timeout(15_000),
    });
    if (!response.ok) throw new Error(`Источник вернул HTTP ${response.status}`);
    const queue = await response.json();
    return normalize(queue, Date.now());
  }

  return { normalize, read, staleAfter: 2 * HOUR };
})();

if (typeof module !== "undefined" && module.exports) module.exports = firstCarCommenting;
if (typeof window !== "undefined") window.firstCarCommenting = firstCarCommenting;
