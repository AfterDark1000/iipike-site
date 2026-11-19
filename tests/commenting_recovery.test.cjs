const { test } = require('node:test');
const assert = require('node:assert/strict');
const { checkRecovery } = require('../scripts/commenting_recovery.cjs');
const { staleAfter } = require('../lab/dzen-first-car/commenting-live.js');

const lastUpdate = '2026-11-19T09:28:44.175726Z';

function api({ error, queue = { schema_version: 1, updated_at: lastUpdate } } = {}) {
  const warnings = [];
  const outputs = {};
  const repo = { owner: 'AfterDark1000', repo: 'iipike-site' };
  return {
    context: { repo }, warnings, outputs,
    github: { rest: { repos: { getContent: async (params) => {
      assert.deepEqual(params, { ...repo, path: 'commenting/queue.json', ref: 'commenting-data' });
      if (error) throw error;
      return { data: { encoding: 'base64', content: Buffer.from(JSON.stringify(queue)).toString('base64') } };
    } } } },
    core: { warning: (text) => warnings.push(text), setOutput: (key, value) => { outputs[key] = value; } },
  };
}

test('watchdog and browser share the 90-minute threshold; only stale data starts fallback', async () => {
  assert.equal(staleAfter, 90 * 60_000);
  const threshold = Date.parse(lastUpdate) + staleAfter;
  for (const [time, due] of [[threshold, false], [threshold + 1, true]]) {
    const handle = api();
    await checkRecovery(handle, time);
    assert.equal(handle.outputs.due, due);
    assert.equal(handle.warnings.length, Number(due));
  }
});

test('missing queue may be initialized; permission and bad timestamp failures leave collection blocked', async () => {
  const noQueue = api({ error: { status: 404 } });
  await checkRecovery(noQueue);
  assert.equal(noQueue.outputs.due, true);
  assert.equal(noQueue.warnings.length, 1);
  const denied = new Error('HTTP 403');
  const unavailable = api({ error: denied });
  await assert.rejects(checkRecovery(unavailable), denied);
  assert.deepEqual(unavailable.outputs, {});
  const invalid = api({ queue: { schema_version: 1, updated_at: 'invalid' } });
  await assert.rejects(checkRecovery(invalid), /Invalid commenting queue timestamp/);
  assert.deepEqual(invalid.outputs, {});
});
