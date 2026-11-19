const assert = require('node:assert/strict');
const { test } = require('node:test');
const { nativeCandidates, normalize } = require('../admin/first-car/commenting-live.js');
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
