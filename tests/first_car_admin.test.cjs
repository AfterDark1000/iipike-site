const assert = require('node:assert/strict');
const { test } = require('node:test');
const { nativeCandidates, normalize, readDzen } = require('../admin/first-car/commenting-live.js');
const watchlist = require('../admin/first-car/watchlist.json');

test('real Dzen observations survive the 24-hour window without inventing counts', () => {
  const current = Date.parse('2026-11-19T18:36:00Z');
  const rows = nativeCandidates(watchlist, current);
  assert.equal(rows.length, 4);
  assert.ok(rows.every((row) => row.comments_open && row.dzen_published_at && row.kind === 'dzen'));
  assert.deepEqual(rows.map((row) => row.comments), [1, 0, 1, 0]);
  assert.deepEqual(nativeCandidates(watchlist, current + 24 * 3_600_000), []);
  assert.deepEqual(nativeCandidates(watchlist, Date.parse('2026-11-19T18:30:00Z')), []);
});

test('publisher drafts never inherit a Dzen publication time from their original', () => {
  const current = Date.parse('2026-11-19T18:36:00Z');
  const q = { schema_version: 1, updated_at: '2026-11-19T17:39:01Z', generator: { status: 'error' },
    sources: [{ id: 'publisher', name: 'Издатель', status: 'ok' }], items: [{
      source_id: 'publisher', title: 'Статья об ИИ', status: 'draft_ready', comment: 'Тестовая реплика',
      published_at: '2026-11-19T09:00:00Z', source_url: 'https://example.org/ai', dzen_url: null,
    }] };
  const result = normalize(q, current);
  assert.equal(result.generator_status, 'error');
  assert.equal(result.candidates.length, 1);
  assert.equal(result.candidates[0].dzen_url, null);
  assert.equal(result.candidates[0].dzen_published_at, null);
  assert.equal(result.candidates[0].publisher_published_at, q.items[0].published_at);
});

test('the authoritative Dzen snapshot uses server time; raw fallback distinguishes 404 from an empty queue', async () => {
  const now = Date.parse('2026-11-20T09:52:00Z');
  const article = { url: 'https://dzen.ru/a/avwsiGM1tFu-0T5x', title: '83 000 просмотров в Threads за месяц',
    source_name: 'GPTнул', source: 'dzen_launcher_more', first_seen_at: '2026-11-20T09:44:05.526Z' };
  const queue = { schema_version: 1, articles: [
    { ...article, published_at: '2026-11-20T07:16:37.000Z' },
    { ...article, url: 'https://dzen.ru/a/expired-item', published_at: '2026-11-19T09:51:59Z' },
  ] };
  const raw404 = async () => new Response(null, { status: 404 });
  const snapshot = await readDzen(raw404, async () => ({ queue, now }));
  assert.deepEqual(snapshot.articles.map(row => row.dzen_url), [article.url]);
  assert.equal(snapshot.articles[0].source_name, 'GPTнул');
  await assert.rejects(readDzen(raw404, async () => { throw Error('route_not_found'); }), /HTTP 404/);
});
