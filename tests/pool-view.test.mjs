import test from "node:test";
import assert from "node:assert/strict";
import {buildRows, counts, selectRows, STATUS_LABELS, DECISION_LABELS}
  from "../admin/pool/pool-data.mjs";

const sample = {
  schema_version: 1, note: "Read only", items: [
    {sequence: 1, id: "n-1", title: "Первая новость", status: "queued", priority: "normal",
      source_url: "https://example.org/1"},
    {sequence: 2, id: "n-2", title: "ИИ и нейросети", status: "queued", priority: "normal"},
    {sequence: 3, id: "n-3", title: "Короткая история", status: "queued", priority: "normal"},
    {sequence: 4, id: "n-4", title: "Отложенное", status: "queued", priority: "normal"},
    {sequence: 5, id: "n-5", title: "Короткая в работе", status: "in_review", priority: "normal"},
    {sequence: 6, id: "n-6", title: "Принятая", status: "approved", priority: "high"},
    {sequence: 7, id: "n-7", title: "Закрытая", status: "rejected", priority: "normal"},
    {sequence: 58, id: "n-58", title: "Контрразведчики OpenAI", status: "queued", priority: "high",
      article_id: "manual-rewrite"},
  ]
};
const routes = {schema_version:1, items:[
  {pool_id:"n-1",sequence:1,lane:"long",decision:"full"},
  {pool_id:"n-2",sequence:2,lane:"long",decision:"hot"},
  {pool_id:"n-3",sequence:3,lane:"short",decision:"short"},
  {pool_id:"n-4",sequence:4,lane:"hold",decision:"defer"},
  {pool_id:"n-5",sequence:5,lane:"short",decision:"short"},
  {pool_id:"n-6",sequence:6,lane:"long",decision:"hot"},
  {pool_id:"n-7",sequence:7,lane:"hold",decision:"manual"},
  {pool_id:"n-58",sequence:58,lane:"long",decision:"hot"}
]};
const ids = array => array.map(x=>x.sequence);

test("combines approved routing without modifying source data", () => {
  const frozen = JSON.stringify([sample, routes]);
  const rows = buildRows(sample, routes);
  assert.equal(rows.length, 8);
  assert.equal(rows[7].decision, "hot");
  assert.equal(rows[7].article_id, "manual-rewrite");
  assert.equal(JSON.stringify([sample,routes]), frozen);
  assert.equal(STATUS_LABELS.approved, "Согласована");
  assert.equal(DECISION_LABELS.defer, "Отложена");
});

test("separates active, completed, and sorter lanes", () => {
  const rows = buildRows(sample, routes), n = counts(rows);
  assert.deepEqual(n,{all:8,queued:5,in_review:1,approved:1,rejected:1,
    active:6,hot:2,full:1,short:2,hold:1});
  assert.deepEqual(ids(selectRows(rows,{view:"active"})),[2,58,1,3,5,4]);
  assert.deepEqual(ids(selectRows(rows,{view:"hot"})),[2,58]);
  assert.deepEqual(ids(selectRows(rows,{view:"short"})),[3,5]);
  assert.deepEqual(ids(selectRows(rows,{view:"hold"})),[4]);
  assert.deepEqual(ids(selectRows(rows,{view:"history"})),[6,7]);
  assert.deepEqual(ids(selectRows(rows,{view:"work"})),[5]);
});

test("supports FIFO, newest-first, sequence and Russian-language search", () => {
  const rows = buildRows(sample, routes);
  assert.deepEqual(ids(selectRows(rows,{view:"active",sort:"fifo"})),[1,2,3,4,5,58]);
  assert.deepEqual(ids(selectRows(rows,{view:"active",sort:"new"})),[58,5,4,3,2,1]);
  assert.deepEqual(ids(selectRows(rows,{view:"all",search:"#58"})),[58]);
  assert.deepEqual(ids(selectRows(rows,{view:"all",search:"контрразведчики"})),[58]);
  assert.deepEqual(ids(selectRows(rows,{view:"all",search:"MANUAL-REWRITE"})),[58]);
  assert.deepEqual(ids(selectRows(rows,{view:"all",search:"отсутствует"})),[]);
});

test("rejects malformed input and mismatched routing instead of inventing statuses", () => {
  assert.throws(()=>buildRows({}, routes), /site_news_pool/);
  assert.throws(()=>buildRows(sample, {}), /editorial_routing/);
  assert.throws(()=>buildRows(sample, {schema_version:1, items:[
    {pool_id:"n-58",sequence:999,lane:"long",decision:"hot"}
  ]}), /Несоответствие/);
  assert.throws(()=>buildRows({...sample,items:[sample.items[0],sample.items[0]]},routes),
    /Повтор новости/);
});
