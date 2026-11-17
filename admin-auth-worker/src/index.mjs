// HPII admin auth/API gateway. Deploy separately; do NOT expose secrets in GitHub Pages.
// GitHub OAuth identity is read-only. Repository write token stays in Worker secrets.
const enc = new TextEncoder();
const dec = new TextDecoder();
const MAX_NOTE = 4000;
const SESSION_SECONDS = 8 * 3600;
const STATE_SECONDS = 600;

function b64url(bytes) {
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}
function unb64url(value) {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new Error("bad base64");
  const text = atob(value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4));
  return Uint8Array.from(text, c => c.charCodeAt(0));
}
const random = () => b64url(crypto.getRandomValues(new Uint8Array(32)));
async function digest(value) {
  return b64url(new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(value))));
}
async function hmac(secret, payload) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), {name:"HMAC",hash:"SHA-256"}, false, ["sign"]);
  return b64url(new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(payload))));
}
async function ticket(secret, data) {
  const raw = b64url(enc.encode(JSON.stringify(data)));
  return raw + "." + await hmac(secret, raw);
}
async function verify(secret, value, kind) {
  if (!value || value.length > 2500) return null;
  const [raw, mac, extra] = value.split(".");
  if (extra !== undefined || !raw || !mac || !/^[A-Za-z0-9_-]+$/.test(mac)) return null;
  const expected = await hmac(secret, raw);
  // Compare signatures without content-dependent short circuiting.
  if (mac.length !== expected.length) return null;
  let diff = 0;
  for (let i=0;i<mac.length;i++) diff |= mac.charCodeAt(i) ^ expected.charCodeAt(i);
  if (diff) return null;
  let data;
  try { data = JSON.parse(dec.decode(unb64url(raw))); } catch { return null; }
  if (!data || data.kind !== kind || !Number.isSafeInteger(data.exp) || data.exp < Math.floor(Date.now()/1000)) return null;
  return data;
}
const noStore = {"cache-control":"no-store", "x-content-type-options":"nosniff", "referrer-policy":"no-referrer", "x-frame-options":"DENY"};
function send(data, status=200, headers={}) {
  return new Response(JSON.stringify(data), {status,headers:{...noStore,"content-type":"application/json; charset=utf-8",...headers}});
}
function fail(status, code, headers={}) { return send({ok:false,error:code},status,headers); }
function origin(req, env) {
  return req.headers.get("Origin") === env.ADMIN_ORIGIN;
}
function cors(env) {
  return {"access-control-allow-origin":env.ADMIN_ORIGIN,"access-control-allow-methods":"GET, POST, OPTIONS","access-control-allow-headers":"Authorization, Content-Type","vary":"Origin"};
}
function configured(env) {
  const required=["ADMIN_ORIGIN","BACKEND_ORIGIN","GITHUB_CLIENT_ID","GITHUB_CLIENT_SECRET","SESSION_SIGNING_KEY","GITHUB_REPO_TOKEN","ALLOWED_GITHUB_USER_ID"];
  return required.every(k=>typeof env[k] === "string" && env[k].length>0)
    && /^https:\/\//.test(env.ADMIN_ORIGIN) && /^https:\/\//.test(env.BACKEND_ORIGIN)
    && env.SESSION_SIGNING_KEY.length >= 32 && env.ADMIN_ORIGIN !== env.BACKEND_ORIGIN;
}
function authCookie(value) {
  return "__Host-hpii_oauth="+value+"; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age="+STATE_SECONDS;
}
const dropCookie = "__Host-hpii_oauth=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0";
function getCookie(request) {
  const found = (request.headers.get("Cookie")||"").match(/(?:^|;\s*)__Host-hpii_oauth=([^;]+)/);
  return found ? found[1] : "";
}
function githubHeaders(token) {
  return {"authorization":"Bearer "+token,"accept":"application/vnd.github+json","x-github-api-version":"2022-11-28","user-agent":"hpii-admin-auth"};
}
async function githubJson(path, env, opts={}) {
  const response = await fetch("https://api.github.com/repos/AfterDark1000/iipike-site"+path,{
    ...opts, headers:{...githubHeaders(env.GITHUB_REPO_TOKEN),...(opts.headers||{})}
  });
  const result = await response.json().catch(()=>({}));
  return {status:response.status,data:result};
}
function pathFor(id) { return "editorial_inbox/auto_drafts/"+id+".json"; }
function savedPath(id,revision) { return "editorial_inbox/auto_decisions/"+id+"-r"+revision+".json"; }
function validReview(d) {
  if (!d || typeof d!=="object" || Array.isArray(d)) return false;
  const keys=Object.keys(d).sort();
  if (JSON.stringify(keys)!==JSON.stringify(["action","article_id","note","revision","updated_at"].sort())) return false;
  return /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(d.article_id) && d.article_id.length <= 80 &&
    Number.isSafeInteger(d.revision) && d.revision >= 1 &&
    ["revise","reject","approve_text"].includes(d.action) &&
    typeof d.updated_at==="string" && d.updated_at.length < 80 &&
    typeof d.note==="string" && d.note.length<=MAX_NOTE &&
    (d.action==="approve_text" || d.note.trim().length>0);
}
function decodeGitHubContent(data) {
  if (!data || data.type!=="file" || !data.sha || typeof data.content!=="string") throw Error("file_missing");
  return JSON.parse(dec.decode(Uint8Array.from(atob(data.content.replace(/\s/g,"")),c=>c.charCodeAt(0))));
}
function encodeGitHubContent(data) {
  return btoa(String.fromCharCode(...enc.encode(JSON.stringify(data,null,2)+"\n")));
}
async function recordReview(env, body, login) {
  if (!validReview(body)) return fail(400,"invalid_decision");
  const ref="editorial-intake";
  const draft=await githubJson("/contents/"+pathFor(body.article_id)+"?ref="+ref,env);
  if (draft.status!==200) return fail(409,"draft_unavailable");
  let value;
  try { value=decodeGitHubContent(draft.data); } catch { return fail(409,"draft_invalid"); }
  if (value.article_id!==body.article_id || value.revision!==body.revision ||
      value.updated_at!==body.updated_at || value.status!=="ready_for_review") {
    return fail(409,"draft_revision_changed");
  }
  const location=savedPath(body.article_id,body.revision);
  const old=await githubJson("/contents/"+location+"?ref="+ref,env);
  if (old.status===200) return fail(409,"decision_exists");
  if (old.status!==404) return fail(502,"github_read_failed");
  const status=body.action==="revise"?"feedback_pending_revision":body.action==="reject"?"rejected":"text_approved_cover_pending";
  const record={
    schema_version:1, article_id:body.article_id, revision:body.revision,
    updated_at:body.updated_at, action:body.action,note:body.note,decided_by:login,
    decided_at:new Date().toISOString(),draft_blob_sha:draft.data.sha,status,
    channel:"hpii-admin-oauth-gateway"
  };
  const write=await githubJson("/contents/"+location,env,{
    method:"PUT",
    headers:{"content-type":"application/json"},
    body:JSON.stringify({branch:ref,message:"review(auto-editor): "+body.article_id+" r"+body.revision,
      content:encodeGitHubContent(record)})
  });
  if (![200,201].includes(write.status)) return fail(write.status===409||write.status===422?409:502,"github_write_failed");
  return send({ok:true,status,article_id:body.article_id,revision:body.revision,
    verification_path:location,commit_sha:write.data.commit?.sha||null});
}
async function login(env) {
  const state=random(), verifier=random(), challenge=await digest(verifier);
  const signed=await ticket(env.SESSION_SIGNING_KEY,{kind:"oauth",state,verifier,exp:Math.floor(Date.now()/1000)+STATE_SECONDS});
  const url=new URL("https://github.com/login/oauth/authorize");
  url.searchParams.set("client_id",env.GITHUB_CLIENT_ID);
  url.searchParams.set("redirect_uri",env.BACKEND_ORIGIN+"/auth/callback");
  url.searchParams.set("scope","read:user");
  url.searchParams.set("state",state);
  url.searchParams.set("code_challenge",challenge);
  url.searchParams.set("code_challenge_method","S256");
  return new Response(null,{status:302,headers:{...noStore,location:url.href,"set-cookie":authCookie(signed)}});
}
async function callback(request,env) {
  const u=new URL(request.url), code=u.searchParams.get("code"), state=u.searchParams.get("state");
  const saved=await verify(env.SESSION_SIGNING_KEY,getCookie(request),"oauth");
  if (!code || !state || !saved || state!==saved.state) return fail(401,"login_expired",{"set-cookie":dropCookie});
  const exchange=await fetch("https://github.com/login/oauth/access_token",{
    method:"POST",headers:{"accept":"application/json","content-type":"application/json"},
    body:JSON.stringify({client_id:env.GITHUB_CLIENT_ID,client_secret:env.GITHUB_CLIENT_SECRET,
      code,redirect_uri:env.BACKEND_ORIGIN+"/auth/callback",code_verifier:saved.verifier})
  });
  const tokens=await exchange.json().catch(()=>({}));
  if (!exchange.ok || !tokens.access_token) return fail(401,"github_oauth_failed",{"set-cookie":dropCookie});
  const response=await fetch("https://api.github.com/user",{headers:githubHeaders(tokens.access_token)});
  const user=await response.json().catch(()=>({}));
  if (!response.ok || String(user.id)!==String(env.ALLOWED_GITHUB_USER_ID) || user.login!=="AfterDark1000") {
    return fail(403,"account_not_allowed",{"set-cookie":dropCookie});
  }
  const token=await ticket(env.SESSION_SIGNING_KEY,{
    kind:"session",user_id:user.id,login:user.login,
    exp:Math.floor(Date.now()/1000)+SESSION_SECONDS
  });
  const nonce=random();
  // No OAuth/GitHub token reaches the browser. Short-lived HMAC session arrives by origin-bound popup messaging.
  const html='<!doctype html><meta charset="utf-8"><title>ХПИИ — вход</title>'+
    '<p>Вход подтверждён. Окно можно закрыть.</p>'+
    '<script nonce="'+nonce+'">if(window.opener){window.opener.postMessage('+JSON.stringify({type:"hpii-auth",token,login:user.login,backend:env.BACKEND_ORIGIN})+','+JSON.stringify(env.ADMIN_ORIGIN)+');window.close()}</script>';
  return new Response(html,{status:200,headers:{...noStore,"content-type":"text/html; charset=utf-8",
    "content-security-policy":"default-src 'none'; script-src 'nonce-"+nonce+"'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "set-cookie":dropCookie}});
}
async function verifySession(req,env) {
  const header=req.headers.get("Authorization")||"";
  if (!header.startsWith("Bearer ")) return null;
  const data=await verify(env.SESSION_SIGNING_KEY,header.slice(7),"session");
  return data && String(data.user_id)===String(env.ALLOWED_GITHUB_USER_ID) && data.login==="AfterDark1000" ? data : null;
}
export default {
  async fetch(request,env) {
    const url=new URL(request.url);
    if (!configured(env)) return fail(503,"gateway_not_configured");
    if (url.origin!==env.BACKEND_ORIGIN) return fail(403,"unexpected_host");
    if (url.pathname==="/auth/start" && request.method==="GET") return login(env);
    if (url.pathname==="/auth/callback" && request.method==="GET") return callback(request,env);
    if (url.pathname==="/health" && request.method==="GET") return send({ok:true,service:"hpii-auth-gateway"});
    if (url.pathname.startsWith("/api/")) {
      if (!origin(request,env)) return fail(403,"origin_not_allowed");
      if (request.method==="OPTIONS") return new Response(null,{status:204,headers:{...noStore,...cors(env)}});
      const headers=cors(env);
      const session=await verifySession(request,env);
      if (!session) return fail(401,"login_required",headers);
      if (url.pathname==="/api/session" && request.method==="GET") {
        return send({ok:true,login:session.login,exp:session.exp},200,headers);
      }
      if (url.pathname==="/api/review" && request.method==="POST") {
        if ((request.headers.get("content-type")||"").split(";")[0].trim()!=="application/json") return fail(415,"json_required",headers);
        const raw=await request.text();
        if (raw.length>8000) return fail(413,"request_too_large",headers);
        let body;
        try { body=JSON.parse(raw); } catch { return fail(400,"bad_json",headers); }
        const result=await recordReview(env,body,session.login);
        const responseHeaders=new Headers(result.headers);
        Object.entries(headers).forEach(([k,v])=>responseHeaders.set(k,v));
        return new Response(result.body,{status:result.status,headers:responseHeaders});
      }
      return fail(404,"route_not_found",headers);
    }
    return fail(404,"route_not_found");
  }
};
// Test-friendly pure validation exports; no secrets.
export const __test = {validReview};
