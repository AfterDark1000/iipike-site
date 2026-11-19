const assert = require('node:assert/strict');
const { test } = require('node:test');
const { claimRecovery, readQueue } = require('../scripts/commenting_recovery.cjs');

const repo = { owner: 'AfterDark1000', repo: 'iipike-site' };
const snapshotTime = Date.parse('2026-11-19T09:28:44.175Z');
const threshold = snapshotTime + 90 * 60_000;

function fakeApi() {
  const state = { sha: 'old', updatedAt: snapshotTime, warning: [], requests: [], statuses: {} };
  const repos = {
    getContent: async (params) => {
      assert.deepEqual(params, { ...repo, path: 'commenting/queue.json', ref: state.sha });
      state.requests.push('read-queue');
      return { data: { encoding: 'base64', content: Buffer.from(JSON.stringify({ schema_version: 1,
        updated_at: new Date(state.updatedAt).toISOString(), usage: { attempted: 23 } })).toString('base64') } };
    },
    listCommitStatusesForRef: async (params) => {
      assert.deepEqual(params, { ...repo, ref: state.sha });
      state.requests.push('read-statuses');
      return state.statuses[state.sha] || [];
    },
    createCommitStatus: async (params) => {
      assert.equal(params.sha, state.sha);
      assert.equal(params.context, 'hpii/commenting-recovery-attempt');
      assert.equal(params.target_url, 'https://github.com/AfterDark1000/iipike-site/actions/runs/1');
      state.requests.push('record-attempt');
      state.statuses[state.sha] = [params];
    },
  };
  const github = { rest: { repos, git: { getRef: async (params) => {
    assert.deepEqual(params, { ...repo, ref: 'heads/commenting-data' });
    return { data: { object: { sha: state.sha } } };
  } } }, paginate: async (fn, params) => fn(params) };
  return { state, github, context: { repo, serverUrl: 'https://github.com', runId: 1 },
    core: { warning: (text) => state.warning.push(text) } };
}

test('fresh snapshots leave no marker and never start recovery', async () => {
  const api = fakeApi();
  assert.equal(await claimRecovery(api, threshold), null);
  assert.deepEqual(api.state.requests, ['read-queue']);
  assert.deepEqual(api.state.warning, []);
});

test('a stale snapshot is claimed once, including when collection did not update the branch', async () => {
  const api = fakeApi();
  const previous = await claimRecovery(api, threshold + 1);
  assert.equal(JSON.parse(previous.toString('utf8')).usage.attempted, 23);
  assert.equal(await claimRecovery(api, threshold + 30 * 60_000), null);
  assert.deepEqual(api.state.requests, ['read-queue', 'read-statuses', 'record-attempt', 'read-queue', 'read-statuses']);

  api.state.sha = 'new';
  api.state.updatedAt = threshold + 1000;
  assert.equal(await claimRecovery(api, api.state.updatedAt + 1000), null);
  assert.ok(await claimRecovery(api, api.state.updatedAt + 90 * 60_000 + 1));
  assert.deepEqual(Object.keys(api.state.statuses), ['old', 'new']);
});

test('reading fails closed on bad data and on failure to record the attempt', async () => {
  const api = fakeApi();
  api.state.updatedAt = threshold + 999;
  await assert.rejects(claimRecovery(api, threshold), /Invalid commenting queue timestamp/);
  api.state.updatedAt = snapshotTime;
  api.github.rest.repos.createCommitStatus = async () => { throw new Error('HTTP 403'); };
  await assert.rejects(claimRecovery(api, threshold + 1), /HTTP 403/);
  assert.deepEqual(api.state.warning, []);
  api.github.rest.repos.getContent = async () => ({ data: { encoding: 'none' } });
  await assert.rejects(readQueue(api.github, repo, 'commenting-data'), /Invalid commenting queue file/);
});
