const ISSUER = "https://token.actions.githubusercontent.com";
const REPOSITORY = "AfterDark1000/iipike-site";
const REF = "refs/heads/main";
const EVENTS = new Set(["schedule", "workflow_dispatch", "workflow_run"]);
const RSA = {name:"RSASSA-PKCS1-v1_5",hash:"SHA-256"};
const DZEN_LINK = /^https:\/\/dzen\.ru\/a\/[A-Za-z0-9_-]{8,100}$/;
const MAX_BYTES = 160_000;
export const DAY = 86_400_000;

export function firstCarTextArticle(env) {
  const id = env.FIRST_CAR_OWNER_TEXT_ARTICLE_ID;
  return typeof id === "string" && /^[A-Za-z0-9_-]{8,100}$/.test(id) ? "https://dzen.ru/a/" + id : null;
}

function decode64(value) {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw Error("Invalid base64url");
  return Uint8Array.from(atob(value.replace(/-/g,"+").replace(/_/g,"/")), char => char.charCodeAt(0));
}

export async function firstCarWorkflowIdentity(request, now = Math.floor(Date.now()/1000)) {
  const authorization = request.headers.get("authorization") ?? "";
  if (!authorization.startsWith("Bearer ") || authorization.length > 12_000) return false;
  try {
    const [head, body, signature, extra] = authorization.slice(7).split(".");
    if (extra !== undefined || !head || !body || !signature) return false;
    const utf8 = new TextDecoder();
    const header = JSON.parse(utf8.decode(decode64(head)));
    const payload = JSON.parse(utf8.decode(decode64(body)));
    if (header.alg !== "RS256" || typeof header.kid !== "string" ||
        payload.iss !== ISSUER || payload.aud !== "hpii-first-car-text" ||
        payload.repository !== REPOSITORY || payload.repository_id !== "1425286669" ||
        payload.ref !== REF || payload.workflow_ref !== `${REPOSITORY}/.github/workflows/commenting-queue.yml@${REF}` ||
        !EVENTS.has(payload.event_name) || payload.runner_environment !== "github-hosted" ||
        !Number.isSafeInteger(payload.exp) || !Number.isSafeInteger(payload.nbf) ||
        payload.exp <= now || payload.nbf > now || payload.exp - payload.nbf > 600) return false;
    const response = await fetch(ISSUER + "/.well-known/jwks", {
      redirect:"manual", signal:AbortSignal.timeout(5000)
    });
    if (!response.ok) return false;
    const {keys} = await response.json();
    const jwk = keys.find(key => key.kid === header.kid && key.kty === "RSA");
    if (!jwk) return false;
    const key = await crypto.subtle.importKey("jwk",jwk,RSA,false,["verify"]);
    return await crypto.subtle.verify(RSA,key,decode64(signature),new TextEncoder().encode(head + "." + body));
  } catch {
    return false;
  }
}

export async function ownerText(request) {
  if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json") return {status:415};
  const decoder = new TextDecoder("utf-8",{fatal:true});
  let size = 0, raw = "";
  try {
    for await (const chunk of request.body ?? []) {
      size += chunk.byteLength;
      if (size > MAX_BYTES) return {status:413};
      raw += decoder.decode(chunk,{stream:true});
    }
    const data = JSON.parse(raw + decoder.decode());
    if (!data || Object.keys(data).length !== 2 || typeof data.url !== "string" ||
        !DZEN_LINK.test(data.url) || typeof data.text !== "string") return {status:400};
    const text = data.text.replace(/\s+/gu," ").trim();
    if (text.length < 350 || text.length > 24_000) return {status:400};
    return {status:200,url:data.url,text};
  } catch {
    return {status:400};
  }
}

export async function privateText(binding, action, entry) {
  const store = binding.get(binding.idFromName("dzen-draft-text"));
  const response = await store.fetch("https://first-car.internal/" + action, {
    signal:AbortSignal.timeout(3000), ...(entry === undefined ? {} : {
      method:"POST", body:JSON.stringify(entry)
    }),
  });
  if (!response.ok) throw Error("First Car text storage unavailable");
  return response.json();
}

export class FirstCarText {
  constructor(state) {
    this.storage = state.storage;
  }

  async fetch(request) {
    const path = new URL(request.url).pathname;
    if (request.method === "GET" && ["/pending","/texts"].includes(path)) {
      const now = Date.now();
      const live = [...(await this.storage.list()).values()].filter(item => item.expires > now);
      return Response.json(path === "/pending" ? live.map(item => item.url) :
        Object.fromEntries(live.map(item => [item.url,item.text])));
    }
    if (request.method !== "POST" || path !== "/submit") return new Response(null,{status:404});
    const entry = await request.json();
    return this.storage.transaction(async transaction => {
      const now = Date.now();
      if (entry.expires <= now) return Response.json({accepted:false,reason:"article_expired"});
      const current = await transaction.get(entry.url);
      if (current?.expires > now) {
        return Response.json(current.text === entry.text ? {accepted:true} : {accepted:false,reason:"text_already_submitted"});
      }
      const live = [...(await transaction.list()).values()].filter(item => item.expires > now);
      if (live.length >= 50) return Response.json({accepted:false,reason:"text_queue_full"});
      await transaction.put(entry.url,entry);
      const alarm = await transaction.getAlarm();
      if (alarm === null || entry.expires < alarm) await transaction.setAlarm(entry.expires);
      return Response.json({accepted:true});
    });
  }

  async alarm() {
    await this.storage.transaction(async transaction => {
      const now = Date.now();
      const entries = [...(await transaction.list()).entries()];
      const expired = entries.filter(([,item]) => item.expires <= now).map(([key]) => key);
      if (expired.length) await transaction.delete(expired);
      const next = Math.min(...entries.map(([,item]) => item.expires).filter(expires => expires > now));
      if (Number.isFinite(next)) await transaction.setAlarm(next);
    });
  }
}
