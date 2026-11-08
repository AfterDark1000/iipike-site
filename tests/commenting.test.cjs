const { test } = require('node:test');
const assert = require('node:assert/strict');
const { validRecords, selectRows, directDzen, fresh, safeURL } = require('../admin/commenting/app.js');
const id = 'a'.repeat(24), other = 'b'.repeat(24), old = 'c'.repeat(24);
const now = Date.parse('2026-11-08T07:00:00Z');
const queue = { max_age_hours: 48, items: [
  { id, source_id: 'ixbt', published_at: '2026-11-08T05:00:00Z', status: 'draft_ready', comment: 'A' },
  { id: other, source_id: 'mk', published_at: '2026-11-08T05:00:00Z', status: 'read_error', comment: '' },
  { id: old, source_id: 'mk', published_at: '2026-11-01T05:00:00Z', status: 'draft_ready', comment: 'B' }
] };
test('no invented Dzen link or stale article in ready queue', () => {
  assert.deepEqual(selectRows(queue, {}, 'ready', 'all', now).map(r => r.id), [id]);
  assert.deepEqual(selectRows(queue, {}, 'linked', 'all', now), []);
  assert.equal(fresh({ published_at: 'tomorrow' }, now, 48), false);
});
test('marking posted removes row from work and keeps it in history', () => {
  const records = validRecords({ [id]: { status: 'posted', text: 'Моя правка' } });
  assert.equal(selectRows(queue, records, 'ready', 'all', now).length, 0);
  assert.equal(selectRows(queue, records, 'history', 'all', now)[0].id, id);
  assert.equal(records[id].text, 'Моя правка');
});
test('manual Dzen URL used only after strict validation', () => {
  assert.equal(directDzen('https://dzen.ru/a/abcdefgh123'), true);
  for (const url of ['javascript:alert(1)', 'https://dzen.ru.evil/a/abcdefgh123', 'https://evil/a/abcdefgh123', 'https://dzen.ru/editor']) assert.equal(directDzen(url), false);
  const records = validRecords({ [id]: { dzen_url: 'https://dzen.ru/a/abcdefgh123' } });
  assert.equal(selectRows(queue, records, 'linked', 'all', now).length, 1);
});
test('import rejects bad records, scripts and arbitrary IDs', () => {
  const records = validRecords({ '__proto__': { status: 'posted' }, 'garbage': { status: 'posted' },
    [id]: { status: 'published', dzen_url: 'javascript:alert(1)', text: 'x'.repeat(2501) },
    [other]: { status: 'skipped', text: 'Отредактировано' } });
  assert.deepEqual(Object.keys(records), [other]);
  assert.equal(safeURL('javascript:alert(1)'), null);
  assert.equal(safeURL('https://user:password@site.test'), null);
});
test('pending errors, source filters and restored marks are independent', () => {
  assert.equal(selectRows(queue, {}, 'pending', 'mk', now)[0].id, other);
  assert.equal(selectRows(queue, {}, 'ready', 'mk', now).length, 0);
  assert.equal(selectRows(queue, { [id]: { status: null } }, 'ready', 'all', now).length, 1);
});
