"use strict";

const assert = require("node:assert/strict");
const { test } = require("node:test");
const { AccessStopped, articleList, collect, fetchChannel, updateDataBranch } = require("../scripts/first_car_dzen_collect.cjs");
const { readDzen } = require("../admin/first-car/commenting-live.js");
const watchlist = require("../admin/first-car/watchlist.json");
const { observations, payload } = require("./fixtures/first-car-gptnul-more.json");

const GPTNUL = watchlist.channels[0];
const oneChannel = { ...watchlist, channels: [GPTNUL] };
const HOUR = 60 * 60_000;
const now = Date.parse("2026-11-20T04:00:00Z");
const url = "https://dzen.ru/a/fixture-article";
const title = "Новая статья об ИИ из тестового ответа";
const fresh = {
  ...payload.items[0], link: url + "?from=channel", title,
  publication_date: String((now - 35 * 60_000) / 1000),
};

test("two saved GPTнул observations have 20 authentic URLs and yield zero new entries", async () => {
  const actual = articleList(payload, GPTNUL);
  assert.equal(new Set(actual.map((row) => row.url)).size, 20);
  const seen = await collect(oneChannel, undefined, { read: async () => payload, clock: () => Date.parse(observations[0].observed_at) });
  const later = Date.parse(observations[1].observed_at);
  assert.equal(actual.filter((row) => later - Date.parse(row.published_at) <= 24 * HOUR).length, 4);
  const again = await collect(oneChannel, seen.queue, { read: async () => payload, clock: () => later });
  assert.equal(again.requests, 1);
  assert.equal(again.processed, 1);
  assert.deepEqual(again.errors, []);
  assert.equal(again.added, 0);
  assert.deepEqual(again.queue.articles, []);
});

test("HTTP 200 with an unrecognized response is an error for every affected channel", async () => {
  const result = await collect(watchlist, undefined, {
    read: (channel) => fetchChannel(channel, async () =>
      new Response(JSON.stringify({ items: [] }), { status: 200, headers: { "Content-Type": "application/json" } })),
    clock: () => now,
  });
  assert.equal(result.requests, 5);
  assert.equal(result.processed, 0);
  assert.equal(result.added, 0);
  assert.deepEqual(result.errors, watchlist.channels.map(({ url }) =>
    ({ channel: url, kind: "format", reason: "Unrecognized channel or response shape" })));
});

test("a valid channel is counted separately from an HTTP 200 with malformed JSON", async () => {
  const second = watchlist.channels[1];
  const result = await collect({ ...watchlist, channels: [GPTNUL, second] }, undefined, {
    read: (channel) => fetchChannel(channel, async () => new Response(
      channel === GPTNUL ? JSON.stringify(payload) : 'invalid: private payload',
      { status: 200, headers: { "Content-Type": "application/json" } },
    )),
    clock: () => now,
  });
  assert.equal(result.processed, 1);
  assert.equal(result.added, 0);
  assert.deepEqual(result.errors, [{ channel: second.url, kind: "format", reason: "Invalid JSON from Dzen" }]);
});

test("a new URL flows through the existing queue reader, deduplicates and expires", async (t) => {
  const changed = { ...payload, items: [fresh, { ...fresh, link: url + "#comments" }, ...payload.items] };
  const previous = await collect(oneChannel, undefined, { read: async () => payload, clock: () => now - HOUR });
  const added = await collect(oneChannel, previous.queue, { read: async () => changed, clock: () => now });
  assert.equal(added.added, 1);
  const [row] = added.queue.articles;
  assert.deepEqual(row, {
    url, title, source_name: GPTNUL.name, source: "dzen_launcher_more",
    published_at: new Date(now - 35 * 60_000).toISOString(), first_seen_at: new Date(now).toISOString(),
  });
  t.mock.method(Date, "now", () => now);
  const visible = await readDzen(async (request, options) => {
    assert.equal(request.pathname, "/AfterDark1000/iipike-site/first-car-data/dzen/queue.json");
    assert.equal(options.cache, "no-store");
    return new Response(JSON.stringify(added.queue));
  });
  assert.equal(visible[0].dzen_url, url);
  assert.equal(visible[0].dzen_published_at, row.published_at);
  assert.equal(visible[0].comments, undefined);
  assert.equal(visible[0].views, undefined);
  const repeat = await collect(oneChannel, added.queue, { read: async () => changed, clock: () => now + HOUR });
  assert.equal(repeat.added, 0);
  assert.deepEqual(repeat.queue.articles, [row]);
  const expired = await collect(oneChannel, repeat.queue, { read: async () => changed, clock: () => now + 24 * HOUR });
  assert.deepEqual(expired.queue.articles, []);
  assert.deepEqual(await readDzen(async () => new Response(null, { status: 404 })), []);
  await assert.rejects(readDzen(async () => new Response(null, { status: 503 })), /503/);
});

test("use the feed-link path for named channels and the publisher ID for ID channels", () => {
  const named = structuredClone(payload);
  named.channel.source.feed_link += "?country_code=ru&clid=1400";
  assert.equal(articleList(named, GPTNUL).length, 20);
  named.channel.source.feed_link = watchlist.channels[1].url;
  assert.throws(() => articleList(named, GPTNUL), /Unrecognized/);
  const byId = watchlist.channels[3];
  const id = byId.url.split("/").at(-1);
  named.channel.source.publisher_id = id;
  named.items = [{ ...fresh, publisher_id: id }, fresh, { ...fresh, publisher_id: id, publication_date: "час назад" }];
  assert.equal(articleList(named, byId).length, 1);
});

test("check at most once per eligible channel with configurable cooldown and request budget", async () => {
  const channels = [];
  const read = async (channel) => {
    channels.push(channel.url);
    return { channel: { status: "ok", source: {
      publisher_id: channel.url.includes("/id/") ? channel.url.split("/").at(-1) : "publisher",
      feed_link: channel.url,
    } }, items: [] };
  };
  const initial = await collect(watchlist, undefined, { read, clock: () => now, maxRequests: 2, intervalMinutes: 90 });
  assert.equal(initial.requests, 2);
  const second = await collect(watchlist, initial.queue, { read, clock: () => now + HOUR });
  assert.equal(second.requests, 3);
  assert.deepEqual(channels, watchlist.channels.map((channel) => channel.url));
  const cached = await collect(watchlist, second.queue, { read, clock: () => now + HOUR + 1 });
  assert.equal(cached.requests, 0);
  await assert.rejects(collect(watchlist, undefined, { intervalMinutes: 59 }), /limits/);
});

test("single request uses no credentials or redirects and rejects access refusals", async () => {
  const byId = watchlist.channels[3];
  await assert.rejects(fetchChannel(byId, async (request, options) => {
    assert.equal(request.origin + request.pathname, "https://dzen.ru/api/v3/launcher/more");
    assert.equal(request.searchParams.get("channel_id"), byId.url.split("/").at(-1));
    assert.equal(options.credentials, "omit");
    assert.equal(options.redirect, "manual");
    assert.ok(options.signal instanceof AbortSignal);
    return new Response(null, { status: 429 });
  }), AccessStopped);
  await assert.rejects(fetchChannel(GPTNUL, async (request) => {
    assert.equal(request.searchParams.get("channel_name"), "gptnul");
    return new Response("<html>Sign in</html>", { headers: { "Content-Type": "text/html" } });
  }), AccessStopped);
});

test("stop on 403/429 or redirect, and never automatically restart a stopped collector", async () => {
  for (const status of [302, 403, 429]) {
    const denied = await collect(watchlist, undefined, {
      read: (channel) => fetchChannel(channel, async () => new Response(null, { status })), clock: () => now,
    });
    assert.equal(denied.requests, 1);
    assert.equal(denied.processed, 0);
    assert.equal(denied.errors[0].kind, "access");
    assert.equal(denied.queue.blocked.status, status);
    const blocked = await collect(watchlist, denied.queue, { clock: () => now + 48 * HOUR });
    assert.equal(blocked.requests, 0);
  }
});

test("transient errors back off and preserve unexpired articles", async () => {
  const read = async () => ({ ...payload, items: [fresh] });
  const good = await collect(oneChannel, undefined, { read, clock: () => now });
  const failed = await collect(oneChannel, good.queue, {
    read: async () => { throw new Error("timeout"); }, clock: () => now + HOUR,
  });
  assert.equal(failed.queue.polls[GPTNUL.url].failures, 1);
  assert.deepEqual(failed.errors, [{ channel: GPTNUL.url, kind: "fetch", reason: "Network request failed or timed out" }]);
  assert.deepEqual(failed.queue.articles, good.queue.articles);
  assert.equal((await collect(oneChannel, failed.queue, { read, clock: () => now + 2 * HOUR })).requests, 0);
  const later = await collect(oneChannel, failed.queue, { read, clock: () => now + 3 * HOUR });
  assert.equal(later.requests, 1);
  assert.equal(later.queue.polls[GPTNUL.url].failures, 0);
});

test("write only the dedicated data ref and do not rewrite unchanged cached state", async () => {
  const branch = "heads/first-car-data";
  let saved;
  const github = { rest: {
    git: {
      getRef: async ({ ref }) => {
        assert.equal(ref, branch);
        if (!saved) throw Object.assign(new Error("not found"), { status: 404 });
        return { data: { object: { sha: "head" } } };
      },
      createTree: async ({ tree }) => {
        assert.deepEqual(tree.map((file) => file.path), ["dzen/queue.json"]);
        assert.equal(saved, undefined);
        saved = tree[0].content;
        return { data: { sha: "tree" } };
      },
      createCommit: async ({ tree, parents }) => {
        assert.equal(tree, "tree");
        assert.deepEqual(parents, []);
        return { data: { sha: "head" } };
      },
      createRef: async ({ ref, sha }) => {
        assert.equal(ref, `refs/${branch}`);
        assert.equal(sha, "head");
      },
    },
    repos: { getContent: async ({ path, ref }) => {
      assert.equal(path, "dzen/queue.json");
      assert.equal(ref, "head");
      return { data: { content: Buffer.from(saved).toString("base64") } };
    } },
  } };
  const options = { read: async () => ({ ...payload, items: [fresh] }), clock: () => now };
  const repo = { owner: "AfterDark1000", repo: "iipike-site" };
  const first = await updateDataBranch(github, repo, oneChannel, options);
  assert.equal(first.added, 1);
  const cached = await updateDataBranch(github, repo, oneChannel, options);
  assert.equal(cached.requests, 0);
  assert.equal(cached.added, 0);
});
