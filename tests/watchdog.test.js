'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {ageMinutes, dueAgeMinutes, evaluateRun, latestNonCancelled,
  evaluatePagesBuilds, selectedReleaseFromLogs, verifySitePublication,
  canAutoCloseIncident} = require('../scripts/watchdog.js');
const NOW = Date.parse('2026-11-06T10:00:00Z');
const run = (date, conclusion='success') => ({created_at:date, status:'completed', conclusion, html_url:'https://github.com/example'});

test('idle healthy workflow is not a failure if latest run succeeded', () => {
  assert.equal(evaluateRun('x',[run('2026-11-06T09:17:00Z')],155,NOW,'url'),null);
});
test('missed schedule creates alert even with last run green', () => {
  assert.match(evaluateRun('x',[run('2026-11-06T06:00:00Z')],155,NOW,'url'),/240 мин/);
});
test('failed newest completed run creates alert', () => {
  assert.match(evaluateRun('x',[run('2026-11-06T09:17:00Z','failure')],155,NOW,'url'),/failure/);
});
test('do not treat cancelled Pages-like run as latest failure', () => {
  assert.equal(latestNonCancelled([run('2026-11-06T09:30:00Z','cancelled'),run('2026-11-06T09:25:00Z')]).conclusion,'success');
});
test('a failed Pages deploy is noticed even if the scheduler is green', () => {
  const pages = [Object.assign(run('2026-11-06T09:30:00Z', 'failure'),
    {name:'pages build and deployment'})];
  assert.match(evaluatePagesBuilds(pages, NOW), /не удалась/);
});
test('replacement Pages deploy suppresses transient cancelled or failed predecessor', () => {
  const failed = Object.assign(run('2026-11-06T09:15:00Z', 'failure'),
    {name:'pages build and deployment'});
  const cancelled = Object.assign(run('2026-11-06T09:25:00Z', 'cancelled'),
    {name:'pages build and deployment'});
  const replacement = {name:'pages build and deployment',
    created_at:'2026-11-06T09:45:00Z',status:'in_progress',conclusion:null};
  assert.equal(evaluatePagesBuilds([replacement,cancelled,failed], NOW), null);
  assert.equal(evaluatePagesBuilds([cancelled, Object.assign(
    run('2026-11-06T09:35:00Z'),{name:'pages build and deployment'}),failed], NOW),null);
});
test('a recent Pages failure gets a grace period; no unrelated-build false alarms', () => {
  const failed=Object.assign(run('2026-11-06T09:55:00Z','failure'),
    {name:'pages build and deployment'});
  assert.equal(evaluatePagesBuilds([failed], NOW),null);
  assert.equal(evaluatePagesBuilds([run('2026-11-06T08:00:00Z','failure')],NOW),null);
});

test('scheduled future slot is not overdue', () => {
  const delay = dueAgeMinutes({readyAt:'2026-11-06T07:00:00Z',notBefore:'2026-11-06T12:00:00+05:00',lastPublication:'2026-11-06T09:30:00Z'},NOW);
  assert.equal(delay,-30);
});
test('spacing from most recent site-first issue applies to pending stories', () => {
  const delay = dueAgeMinutes({readyAt:'2026-11-05T21:00:00Z',notBefore:null,lastPublication:'2026-11-06T09:30:00Z'},NOW);
  assert.equal(delay,-30);
});
test('stalled queue is detected only after both earliest time and spacing', () => {
  const delay = dueAgeMinutes({readyAt:'2026-11-06T06:00:00Z',notBefore:'2026-11-06T12:00:00+05:00',lastPublication:'2026-11-06T07:00:00Z'},NOW);
  assert.equal(delay,120);
});
test('bad timestamps do not yield false overdue queue alarms',()=>{
  assert.equal(dueAgeMinutes({readyAt:'not a date'},NOW),-Infinity);
  assert.equal(ageMinutes('2026-11-06T08:00:00Z',NOW),120);
});

test('actual publishing step is distinguished from fake test releases in job logs', () => {
  const logs = [
    '2026-11-07T18:00:00Z SCHEDULED_RELEASE: first urgent=False',
    '2026-11-07T18:00:50Z ##[group]Run python3 scripts/site_publication_queue.py',
    '2026-11-07T18:00:51Z SCHEDULED_RELEASE: musk-baron-robots-orbital-ai-20261106 urgent=False',
    "2026-11-07T18:00:52Z Site-first release rejected: Quote needs '> ' prefix on line 10",
  ].join('\n');
  assert.equal(selectedReleaseFromLogs(logs), 'musk-baron-robots-orbital-ai-20261106');
  const newFormat=[
    '2026-11-09T17:45:40Z SCHEDULED_RELEASE: fake-from-unit-tests urgent=False',
    '2026-11-09T17:45:41Z ##[group]Run set -o pipefail',
    '2026-11-09T17:45:41Z python3 scripts/site_publication_queue.py | tee /tmp/hpii-site-release.log',
    '2026-11-09T17:45:43Z SCHEDULED_RELEASE: voice-deepfake-family-money-scam-guide-20261109 urgent=False',
    '2026-11-09T17:45:44Z EXISTING_RELEASE_REVIEW_REQUIRED: voice-deepfake-family-money-scam-guide-20261109'
  ].join('\\n');
  assert.equal(selectedReleaseFromLogs(newFormat), 'voice-deepfake-family-money-scam-guide-20261109');
  assert.equal(selectedReleaseFromLogs('SCHEDULED_RELEASE: fake urgent=False'), null);
  assert.equal(selectedReleaseFromLogs(
    '##[group]Run python3 scripts/site_publication_queue.py\nNO_DUE_STORY'), null);
  assert.equal(selectedReleaseFromLogs(
    '##[group]Run python3 scripts/site_publication_queue.py\n' +
    'SCHEDULED_RELEASE: one urgent=False\nSCHEDULED_RELEASE: two urgent=False'), null);
});
test('a successful next cron NEVER closes a failed per-article release', async () => {
  const id = 'musk-baron-robots-orbital-ai-20261106';
  const key = 'site-release:' + id;
  const findings = new Map();
  const checked = new Set(['site-scheduler-heartbeat', 'site-queue']);
  assert.equal(await canAutoCloseIncident(key, findings, checked,
    async () => ({ok:false,why:'not in news.json'})), false);
  assert.equal(await canAutoCloseIncident('site-scheduler', findings, checked,
    async () => ({ok:true})), false);
  assert.equal(await canAutoCloseIncident('site-scheduler-heartbeat',
    findings, checked, async () => ({ok:false})), true);
  assert.equal(await canAutoCloseIncident(key, new Map([[key, 'still failed']]), checked,
    async () => ({ok:true})), false);
  assert.equal(await canAutoCloseIncident(key, findings, checked,
    async () => ({ok:true})), true);
});
test('delivery proof needs a site-first record AND an actual canonical HTML page', async () => {
  const id='musk-baron-robots-orbital-ai-20261106';
  const url='https://iipike.ru/articles/' + id + '/';
  const record={published_site_first:[{id,published_at_utc:'2026-11-07T20:45:34Z'}]};
  const good=async () => ({status:200,text:async()=>'<link rel="canonical" href="' +
    url + '"><meta property="article:published_time" content="2026-11-07T20:45:34Z">'});
  assert.equal((await verifySitePublication(id,record,good)).ok,true);
  assert.equal((await verifySitePublication(id,{published_site_first:[]},good)).ok,false);
  assert.equal((await verifySitePublication(id,record,
    async () => ({status:404,text:async()=>''}))).ok,false);
  assert.equal((await verifySitePublication(id,record,
    async () => ({status:200,text:async()=>'<html>Homepage instead</html>'}))).ok,false);
  assert.equal((await verifySitePublication(id,{check_error:'git fetch failed'},good)).ok,false);
  assert.equal((await verifySitePublication('../unsafe',record,good)).ok,false);
});
