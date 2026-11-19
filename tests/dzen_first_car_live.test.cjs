const { test } = require('node:test');
const assert = require('node:assert/strict');
const { normalize, read, staleAfter } = require('../lab/dzen-first-car/commenting-live.js');
const queue = require('../lab/dzen-first-car/fixtures/commenting-queue-2026-11-19.json');

test('uses the current 24-hour window even if the source retains 48 hours', () => {
  const now = Date.parse('2026-11-19T12:05:27Z');
  const result = normalize(queue, now);
  assert.equal(result.candidates.length, 3);
  assert.ok(result.candidates.every((row) => row.draft_comment && !row.dzen_url && row.dzen_published_at === null));
  assert.deepEqual(result.failed, ['МК']);
  assert.ok(now - Date.parse(result.updated_at) > staleAfter);
  assert.deepEqual(normalize(queue, now + 24 * 3_600_000).candidates, []);
});

test('validates links, ignores future and undated rows, and deduplicates canonical originals', () => {
  const now = Date.parse('2026-11-19T12:05:27Z');
  const ready = queue.items[0];
  const result = normalize({ ...queue, items: [ready, { ...ready, source_url: ready.source_url + '#other' },
    { ...ready, source_url: 'javascript:alert(1)' }, { ...ready, source_url: 'https://u@example.org/a' },
    { ...ready, source_url: 'https://example.org/future', published_at: '2026-11-20T08:00:00Z' },
    { ...ready, source_url: 'https://example.org/undated', published_at: null },
    { ...ready, source_url: 'https://example.org/other', source_id: 'disabled' },
    { ...ready, source_url: 'https://example.org/mirror', dzen_url: 'https://dzen.ru/a/av3TvaCL2QDF_wYt' },
  ] }, now);
  assert.equal(result.candidates.length, 2);
  assert.equal(result.candidates[1].dzen_url, 'https://dzen.ru/a/av3TvaCL2QDF_wYt');
  assert.equal(result.candidates[1].dzen_published_at, null);
});

test('requests only the public commenting JSON without cache or credentials and surfaces failures', async () => {
  await assert.rejects(read(async (url, options) => {
    assert.equal(url.origin + url.pathname,
      'https://raw.githubusercontent.com/AfterDark1000/iipike-site/commenting-data/commenting/queue.json');
    assert.ok(url.searchParams.get('t'));
    assert.equal(options.credentials, 'omit');
    assert.equal(options.cache, 'no-store');
    assert.equal(options.mode, 'cors');
    return { ok: false, status: 503 };
  }), /HTTP 503/);
  await assert.rejects(read(async () => ({ ok: true, json: async () => ({}) })), /Некорректный снимок/);
});
