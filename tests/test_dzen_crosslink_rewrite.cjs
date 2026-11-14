'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {createResolver} = require('../scripts/dzen_crosslink_rewrite.cjs');

const slug = 'cnas-sovereign-agents-20261103';
const ident = '6aebfc1cb3220418d3d33244';
const dzen = 'https://dzen.ru/a/auv8HLMiBBjT0zJE';
const site = 'https://iipike.ru/articles/' + slug + '/';
const evidence = {dzen_id:ident, dzen_url:dzen, title:'ИИ-агенты могут стать неотключаемыми',
  status:'published_observed_in_feed'};
const local = {id:slug, title:evidence.title, site_first_dzen_id:ident, site_first_dzen_url:dzen};

test('CNAS site link becomes its exact verified Dzen counterpart', () => {
  const body = 'CNAS в [докладе о «суверенных» ИИ-агентах](' + site + ') описал сценарий.';
  const result = createResolver([local], [evidence])(body);
  assert.equal(result.text, body.replace(site, dzen));
  assert.equal(result.rewritten, 1);
  assert.deepEqual(result.unresolved, []);
});

test('historical articles with dzen_id use the same verified mapping', () => {
  const result = createResolver([{id:slug, dzen_id:ident, dzen_url:dzen}], [evidence])(
    '[Доклад](' + site + ')');
  assert.equal(result.text, '[Доклад](' + dzen + ')');
});

test('unmatched site crosslinks remain visible for manual review', () => {
  const text = '[проверить](https://iipike.ru/articles/other-story-20261114/)';
  const result = createResolver([local], [evidence])(text);
  assert.equal(result.text, text);
  assert.equal(result.rewritten, 0);
  assert.deepEqual(result.unresolved, ['other-story-20261114']);
});

test('never accept an unobserved or mismatched Dzen counterpart', () => {
  const input = '[CNAS](' + site + ')';
  for (const rejected of [
    {...evidence, status:'queued'},
    {...evidence, dzen_url:'https://dzen.ru/a/other-id-000000'},
    {...evidence, dzen_id:'111111111111111111111111'},
  ]) {
    const result = createResolver([local], [rejected])(input);
    assert.equal(result.text, input);
    assert.deepEqual(result.unresolved, [slug]);
  }
});

test('duplicate catalog evidence does not select an arbitrary result', () => {
  const result = createResolver([local], [evidence,evidence])('[CNAS](' + site + ')');
  assert.deepEqual(result.unresolved, [slug]);
  assert.equal(result.rewritten, 0);
});

test('preserve Markdown, other destinations and raw URLs', () => {
  const content = '**Жирный** и [CNAS](' + site + '?utm_source=x)\n' +
    '[Первоисточник](https://www.cnas.org/report) и https://iipike.ru/articles/' + slug + '/\n' +
    '[Дзен](' + dzen + ')';
  const result = createResolver([local], [evidence])(content);
  assert.equal(result.text, content.replace(site + '?utm_source=x', dzen));
  assert.equal(result.rewritten, 1);
});

test('reject non-Markdown input instead of silently discarding it', () => {
  const rewrite = createResolver([local], [evidence]);
  assert.throws(() => rewrite(null), TypeError);
});
