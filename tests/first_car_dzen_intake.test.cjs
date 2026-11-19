"use strict";

const assert = require("node:assert/strict");
const { test } = require("node:test");
const { addArticle, publishArticle } = require("../scripts/first_car_dzen_intake.cjs");
const { intakeCandidates, readIntake } = require("../admin/first-car/commenting-live.js");
const watchlist = require("../admin/first-car/watchlist.json");

const now = Date.parse("2026-11-20T10:00:00Z");
const day = 24 * 60 * 60 * 1000;
const url = "https://dzen.ru/a/test-article";
const input = { channel: "gptnul", title: "Тестовая статья об ИИ", article_url: url + "?share=1", confirmed: true };
const emptyState = { schema_version: 1, articles: [], first_seen: {} };

test("a confirmed link enters the existing Dzen queue with unknown metrics and expires from first detection", async () => {
  const saved = addArticle(emptyState, watchlist, input, now);
  const raw = await readIntake(async (request, options) => {
    assert.equal(request.pathname, "/AfterDark1000/iipike-site/first-car-data/dzen/queue.json");
    assert.equal(options.cache, "no-store");
    assert.equal(options.credentials, "omit");
    return new Response(JSON.stringify(saved));
  });
  const [article] = intakeCandidates(raw, now);
  assert.equal(article.dzen_url, url);
  assert.equal(article.source_name, "GPTнул");
  assert.equal(article.dzen_published_at, null);
  assert.equal(article.first_seen_at, new Date(now).toISOString());
  assert.equal(article.comments, undefined);
  assert.equal(article.views, undefined);
  assert.deepEqual(intakeCandidates(raw, now + day + 1), []);
  assert.deepEqual(await readIntake(async () => new Response(null, { status: 404 })), []);
  await assert.rejects(readIntake(async () => new Response(null, { status: 503 })), /503/);
});

test("respect verified publication age and retain deduplication after expiry", () => {
  const published_at = new Date(now - 60_000).toISOString();
  const saved = addArticle(emptyState, watchlist, { ...input, published_at }, now);
  assert.equal(intakeCandidates(saved.articles, now)[0].dzen_published_at, published_at);
  assert.deepEqual(intakeCandidates(saved.articles, now + day), []);
  const updated = addArticle(saved, watchlist, { ...input, article_url: "https://dzen.ru/a/another-test" }, now + day);
  assert.equal(updated.articles.length, 1);
  assert.equal(updated.first_seen[url], saved.first_seen[url]);
  assert.equal(addArticle(updated, watchlist, input, now + day), null);
  assert.equal(addArticle(emptyState, watchlist, { ...input, article_url: watchlist.articles[0].url }, now), null);
});

test("reject unsupported channels, redirects, and unconfirmed or invalid dates", () => {
  for (const invalid of [
    { channel: "other" },
    { article_url: "https://dzen.ru.example/a/test-article" },
    { article_url: "https://dzen.ru/b/test-article" },
    { confirmed: "false" },
    { published_at: "2026-11-19T10:00:00" },
    { published_at: "2026-11-19T09:59:59Z" },
    { published_at: "2026-11-20T10:00:01Z" },
  ]) {
    assert.throws(() => addArticle(emptyState, watchlist, { ...input, ...invalid }, now));
  }
});

test("publish retries only a concurrent ref update, preserving the other insertion", async () => {
  const other = "https://dzen.ru/a/concurrent-test";
  const state = addArticle(emptyState, watchlist, { ...input, article_url: other });
  const written = [];
  let head = "initial";
  const repo = { owner: "AfterDark1000", repo: "iipike-site" };
  const gitHub = { rest: {
    repos: { getContent: async ({ path, ref }) => {
      assert.equal(path, "dzen/queue.json");
      assert.equal(ref, head);
      const previous = ref === "initial" ? emptyState : state;
      return { data: { content: Buffer.from(JSON.stringify(previous)).toString("base64") } };
    } },
    git: {
      getRef: async ({ ref }) => {
        assert.equal(ref, "heads/first-car-data");
        return { data: { object: { sha: head } } };
      },
      createTree: async ({ tree }) => {
        assert.equal(tree.length, 1);
        assert.equal(tree[0].path, "dzen/queue.json");
        written.push(JSON.parse(tree[0].content));
        return { data: { sha: "tree" } };
      },
      createCommit: async ({ parents }) => {
        assert.deepEqual(parents, [head]);
        return { data: { sha: "new" } };
      },
      updateRef: async ({ ref, force }) => {
        assert.equal(ref, "heads/first-car-data");
        assert.equal(force, false);
        if (head === "initial") {
          head = "concurrent";
          throw Object.assign(new Error("Not a fast forward"), { status: 422 });
        }
        head = "new";
      },
    },
  } };
  assert.equal(await publishArticle(gitHub, repo, watchlist, input), true);
  assert.equal(head, "new");
  assert.deepEqual(written.map((s) => s.articles.map((row) => row.url)), [[url], [other, url]]);
});
