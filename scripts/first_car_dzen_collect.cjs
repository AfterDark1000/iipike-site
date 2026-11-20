"use strict";

const MINUTE = 60_000;
const DAY = 24 * 60 * MINUTE;
const BASELINE = Date.parse("2026-11-19T19:41:32Z");
const SOURCE = "dzen_launcher_more";
const ENDPOINT = "https://dzen.ru/api/v3/launcher/more";
const MAX_BODY = 1024 * 1024;
const DATA_REF = "heads/first-car-data";
const DATA_PATH = "dzen/queue.json";

function channelRequest(channel) {
  const match = /^https:\/\/dzen\.ru\/(?:(id)\/)?([a-z0-9_.-]+)$/i.exec(channel.url);
  if (!match) throw new Error("Unsupported channel URL in the watchlist");
  const [, id, key] = match;
  const url = new URL(ENDPOINT);
  url.search = new URLSearchParams([
    ["country_code", "ru"], [id ? "channel_id" : "channel_name", key],
    ["sort_type", "regular"], ["country_code", "ru"], ["clid", "1400"],
    ["lang", "ru"], ["channel_version", "subscriptions"],
  ]);
  return { url, id: id ? key : null };
}

function canonicalArticle(link) {
  if (typeof link !== "string") return null;
  const match = /^(https:\/\/dzen\.ru\/a\/[A-Za-z0-9_-]{8,100})\/?(?:[?#].*)?$/.exec(link);
  return match?.[1] ?? null;
}

function articleList(payload, channel) {
  const source = payload?.channel?.source;
  const { id } = channelRequest(channel);
  const publisher = source?.publisher_id;
  const feed = typeof source?.feed_link === "string" ? source.feed_link.split(/[?#]/, 1)[0].replace(/\/$/, "") : null;
  if (payload?.channel?.status !== "ok" || typeof publisher !== "string" || !publisher ||
      (id ? id !== publisher : feed !== channel.url) ||
      !Array.isArray(payload?.items) || payload.items.length > 50) {
    throw new Error("Unrecognized channel or response shape");
  }
  return payload.items.flatMap((item) => {
    if (item?.publisher_id !== publisher || item.item_type !== "native") return [];
    const url = canonicalArticle(item.link);
    const title = typeof item.title === "string" ? item.title.trim() : "";
    const seconds = String(item.publication_date ?? "");
    if (!url || !title || title.length > 500 || !/^\d{10}$/.test(seconds)) return [];
    return [{ url, title, published_at: new Date(Number(seconds) * 1000).toISOString() }];
  });
}

class AccessStopped extends Error {
  constructor(status, reason) {
    super(reason);
    this.status = status;
  }
}

async function fetchChannel(channel, fetcher = fetch) {
  const { url } = channelRequest(channel);
  const response = await fetcher(url, {
    headers: { Accept: "application/json", "User-Agent": "iipike-first-car-collector/1.0" },
    credentials: "omit", redirect: "manual", signal: AbortSignal.timeout(12_000),
  });
  const status = response.status;
  const dispose = () => response.body?.cancel();
  if ([401, 403, 429].includes(status) || (status >= 300 && status < 400)) {
    await dispose();
    throw new AccessStopped(status, "Access refusal, rate limit or redirect from Dzen");
  }
  if (!response.ok) {
    await dispose();
    throw new Error(`Dzen HTTP ${status}`);
  }
  if (!/^application\/json(?:\s*;|$)/i.test(response.headers.get("content-type") ?? "")) {
    await dispose();
    throw new AccessStopped(status, "Unexpected non-JSON response from Dzen");
  }
  const chunks = [];
  let length = 0;
  for await (const chunk of response.body) {
    length += chunk.byteLength;
    if (length > MAX_BODY) throw new Error("Dzen response exceeds 1 MiB");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function emptyQueue() {
  return { schema_version: 1, articles: [], polls: {}, blocked: null };
}

async function collect(watchlist, previous = emptyQueue(), {
  read = fetchChannel, clock = Date.now, intervalMinutes = 60, maxRequests = 5,
} = {}) {
  if (!Number.isInteger(intervalMinutes) || intervalMinutes < 60 || !Number.isInteger(maxRequests)
      || maxRequests < 1 || maxRequests > 5) throw new Error("Invalid collection limits");
  if (previous.schema_version !== 1 || !Array.isArray(previous.articles) ||
      !previous.polls || Object.getPrototypeOf(previous.polls) !== Object.prototype) {
    throw new Error("Invalid previous Dzen queue");
  }
  const channels = watchlist.channels.slice(0, 5);
  channels.forEach(channelRequest);
  const start = clock();
  const interval = intervalMinutes * MINUTE;
  const articles = new Map(previous.articles.map((row) => [row.url, row]));
  const known = new Set(watchlist.articles.map((row) => canonicalArticle(row.url)));
  const polls = { ...previous.polls };
  let blocked = previous.blocked;
  let requests = 0;
  let added = 0;
  for (const channel of channels) {
    if (blocked || requests >= maxRequests) break;
    const poll = polls[channel.url];
    const lastAttempt = Date.parse(poll?.attempted_at);
    const nextAttempt = Date.parse(poll?.next_at);
    const began = clock();
    if (lastAttempt + interval > began || nextAttempt > began) continue;
    requests += 1;
    let failures = 0;
    try {
      const rows = articleList(await read(channel), channel);
      const detected = clock();
      for (const row of rows) {
        const published = Date.parse(row.published_at);
        if (known.has(row.url) || articles.has(row.url) || published <= BASELINE ||
            published > detected || detected - published > DAY) continue;
        articles.set(row.url, {
          ...row, source_name: channel.name, first_seen_at: new Date(detected).toISOString(), source: SOURCE,
        });
        added += 1;
      }
    } catch (error) {
      if (error instanceof AccessStopped) {
        blocked = { status: error.status, reason: error.message, at: new Date(clock()).toISOString() };
      } else {
        failures = Math.min((poll?.failures ?? 0) + 1, 5);
      }
    }
    polls[channel.url] = {
      attempted_at: new Date(began).toISOString(), failures,
      next_at: new Date(began + Math.max(interval, Math.min(interval * 2 ** failures, DAY))).toISOString(),
    };
  }
  const active = [...articles.values()].filter((row) => Date.parse(row.published_at) >= start - DAY);
  active.sort((a, b) => b.published_at.localeCompare(a.published_at));
  return { queue: { schema_version: 1, articles: active, polls, blocked }, requests, added };
}

async function updateDataBranch(github, repo, watchlist, options) {
  let head;
  try {
    head = (await github.rest.git.getRef({ ...repo, ref: DATA_REF })).data.object.sha;
  } catch (error) {
    if (error.status !== 404) throw error;
  }
  let previous = emptyQueue();
  if (head) {
    const { data } = await github.rest.repos.getContent({ ...repo, path: DATA_PATH, ref: head });
    previous = JSON.parse(Buffer.from(data.content, "base64").toString("utf8"));
  }
  const result = await collect(watchlist, previous, options);
  if (JSON.stringify(previous) === JSON.stringify(result.queue)) return result;
  const tree = await github.rest.git.createTree({ ...repo, tree: [{
    path: DATA_PATH, mode: "100644", type: "blob", content: JSON.stringify(result.queue, null, 2) + "\n",
  }] });
  const commit = await github.rest.git.createCommit({
    ...repo, message: "first-car: refresh Dzen links",
    tree: tree.data.sha, parents: head ? [head] : [],
  });
  const sha = commit.data.sha;
  if (head) await github.rest.git.updateRef({ ...repo, ref: DATA_REF, sha, force: false });
  else await github.rest.git.createRef({ ...repo, ref: `refs/${DATA_REF}`, sha });
  return result;
}

module.exports = { AccessStopped, articleList, collect, fetchChannel, updateDataBranch };
