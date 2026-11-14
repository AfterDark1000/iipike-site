'use strict';

function createResolver(news, catalogEntries) {
  // Never infer a Dzen link from a headline or from an unobserved Dzen ID.
  if (!Array.isArray(news) || !Array.isArray(catalogEntries)) {
    throw new TypeError('Dzen crosslink resolver requires both published catalogs');
  }
  const verified = new Map();
  for (const entry of catalogEntries) {
    if (!entry || entry.status !== 'published_observed_in_feed' ||
        !/^[a-f0-9]{24}$/.test(entry.dzen_id || '') ||
        !/^https:\/\/dzen\.ru\/a\/[A-Za-z0-9_-]+$/.test(entry.dzen_url || '') ||
        !entry.title) continue;
    if (!verified.has(entry.dzen_id)) verified.set(entry.dzen_id, []);
    verified.get(entry.dzen_id).push(entry.dzen_url);
  }
  const published = new Map();
  for (const row of news) {
    if (!row || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(row.id || '')) continue;
    const pairs = [[row.dzen_id, row.dzen_url],
                   [row.site_first_dzen_id, row.site_first_dzen_url]]
      .filter(pair => pair[0] || pair[1]);
    if (pairs.length !== 1) continue;
    const [id, url] = pairs[0];
    const trusted = verified.get(id);
    if (trusted && trusted.length === 1 && trusted[0] === url) {
      published.set(row.id, url);
    }
  }
  return function rewriteDzenLinks(markdown) {
    if (typeof markdown !== 'string') throw new TypeError('Expected Dzen Markdown');
    const unresolved = new Set();
    let rewritten = 0;
    const text = markdown.replace(
      /\]\(https:\/\/iipike\.ru\/articles\/([a-z0-9]+(?:-[a-z0-9]+)*)\/(?:[?#][^)\s]*)?\)/g,
      (match, id) => {
        const target = published.get(id);
        if (!target) { unresolved.add(id); return match; }
        rewritten += 1;
        return '](' + target + ')';
      }
    );
    return {text, rewritten, unresolved: [...unresolved]};
  };
}

module.exports = {createResolver};
