"use strict";

const AUDIENCE = "hpii-first-car-text";
const GATEWAY = "https://hpii-admin-gateway.svuktablet.workers.dev/api/first-car/workflow-text";

async function readSubmittedText({ env = process.env, fetcher = fetch, signal = AbortSignal.timeout(10_000) } = {}) {
  const issuer = new URL(env.ACTIONS_ID_TOKEN_REQUEST_URL);
  const requestToken = env.ACTIONS_ID_TOKEN_REQUEST_TOKEN;
  if (issuer.protocol !== "https:" || !issuer.hostname.endsWith(".actions.githubusercontent.com") ||
      issuer.port || issuer.username || issuer.password || !requestToken) throw Error("Missing GitHub OIDC identity");
  issuer.searchParams.set("audience", AUDIENCE);
  const request = (url, token) => fetcher(url, {
    headers: { authorization: "Bearer " + token, accept: "application/json" },
    redirect: "error", signal,
  });
  const identity = await request(issuer, requestToken);
  if (!identity.ok) throw Error(`GitHub OIDC unavailable (HTTP ${identity.status})`);
  const { value } = await identity.json();
  if (typeof value !== "string" || !/^[\w-]+\.[\w-]+\.[\w-]+$/.test(value) || value.length > 12_000) {
    throw Error("Invalid GitHub OIDC identity");
  }
  const response = await request(GATEWAY, value);
  if (!response.ok) throw Error(`First Car text unavailable (HTTP ${response.status})`);
  const { ok, texts } = await response.json();
  if (ok !== true || !texts || typeof texts !== "object" || Array.isArray(texts)) throw Error("Invalid text input");
  const entries = Object.entries(texts);
  if (entries.length > 1 || entries.some(([url, text]) => !/^https:\/\/dzen\.ru\/a\/[A-Za-z0-9_-]{8,100}$/.test(url) ||
      typeof text !== "string" || text.length < 350 || text.length > 24_000)) throw Error("Invalid text input");
  return texts;
}

module.exports = { readSubmittedText };
