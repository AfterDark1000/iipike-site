'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {ageMinutes, dueAgeMinutes, evaluateRun, latestNonCancelled} = require('../scripts/watchdog.js');
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
