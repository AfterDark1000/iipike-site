"use strict";

const BRANCH = "first-car-data";
const PATH = "dzen/queue.json";
const DAY = 24 * 60 * 60 * 1000;
const ARTICLE = /^\/a\/[A-Za-z0-9_-]{8,100}\/?$/;
const ZONED = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

function canonicalArticle(value) {
  let url;
  try { url = new URL(value); } catch { throw new Error("Нужна прямая ссылка на статью Дзена"); }
  if (url.origin !== "https://dzen.ru" || url.username || url.password || !ARTICLE.test(url.pathname)) {
    throw new Error("Нужна прямая ссылка на статью Дзена");
  }
  return url.origin + url.pathname.replace(/\/$/, "");
}

function addArticle(state, watchlist, input, now = Date.now()) {
  const url = canonicalArticle(input.article_url);
  const channel = watchlist.channels.find(({ url }) => url === `https://dzen.ru/${input.channel}`);
  if (!channel) throw new Error("Канал отсутствует в приоритетном списке");
  if (input.confirmed !== true) throw new Error("Подтверди канал, ИИ-тему и публикацию за последние 24 часа");
  const title = (input.title ?? "").trim().replace(/\s+/g, " ");
  if (!title || title.length > 250) throw new Error("Укажи заголовок статьи до 250 символов");
  if (state.schema_version !== 1 || !Array.isArray(state.articles) ||
      !state.first_seen || Object.getPrototypeOf(state.first_seen) !== Object.prototype) {
    throw new Error("Не удалось прочитать сохранённую очередь Дзена");
  }
  if (Object.hasOwn(state.first_seen, url) || watchlist.articles.some((row) => row.url === url)) return null;

  const verifiedTime = (input.published_at ?? "").trim();
  const published = verifiedTime ? Date.parse(verifiedTime) : null;
  if (verifiedTime && (!ZONED.test(verifiedTime) || !(now - DAY <= published && published <= now))) {
    throw new Error("Дата должна содержать часовой пояс и попадать в последние 24 часа");
  }
  const detected = new Date(now).toISOString();
  const articles = state.articles.filter((row) => Date.parse(row.published_at ?? row.first_seen_at) >= now - DAY);
  articles.push({
    url, title, channel_url: channel.url, source_name: channel.name, source: "manual_dzen",
    first_seen_at: detected,
    published_at: published === null ? null : new Date(published).toISOString(),
  });
  return { schema_version: 1, first_seen: { ...state.first_seen, [url]: detected }, articles };
}

async function publishArticle(gitHub, repo, watchlist, input) {
  const ref = `heads/${BRANCH}`;
  const receivedAt = Date.now();
  for (let attempt = 0; attempt < 3; attempt += 1) {
    let head;
    try { head = (await gitHub.rest.git.getRef({ ...repo, ref })).data.object.sha; }
    catch (error) { if (error.status !== 404) throw error; }
    let state = { schema_version: 1, first_seen: {}, articles: [] };
    if (head) {
      const previous = (await gitHub.rest.repos.getContent({ ...repo, path: PATH, ref: head })).data;
      state = JSON.parse(Buffer.from(previous.content, "base64").toString("utf8"));
    }
    const updated = addArticle(state, watchlist, input, receivedAt);
    if (!updated) return false;
    const tree = await gitHub.rest.git.createTree({ ...repo, tree: [{
      path: PATH, mode: "100644", type: "blob", content: JSON.stringify(updated, null, 2) + "\n",
    }] });
    const commit = await gitHub.rest.git.createCommit({
      ...repo, message: "first-car: register a confirmed Dzen article",
      tree: tree.data.sha, parents: head ? [head] : [],
    });
    try {
      const sha = commit.data.sha;
      if (head) await gitHub.rest.git.updateRef({ ...repo, ref, sha, force: false });
      else await gitHub.rest.git.createRef({ ...repo, ref: `refs/${ref}`, sha });
      return true;
    } catch (error) {
      // Retry only after an actual concurrent update to this data branch.
      if (![409, 422].includes(error.status) || attempt === 2) throw error;
      const current = (await gitHub.rest.git.getRef({ ...repo, ref })).data.object.sha;
      if (current === head) throw error;
    }
  }
}

module.exports = { addArticle, publishArticle };
