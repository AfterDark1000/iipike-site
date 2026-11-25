// HPII admin auth/API gateway. Deploy separately; do NOT expose secrets in GitHub Pages.
// GitHub OAuth identity is read-only. Repository write token stays in Worker secrets.
import {DAY, firstCarTextArticle, firstCarWorkflowIdentity, ownerText, privateText} from "./first-car-text.mjs";
export {FirstCarText} from "./first-car-text.mjs";

const enc = new TextEncoder();
const dec = new TextDecoder();
const MAX_NOTE = 4000;
// IDEA-004: seven-day fixed owner session, never indefinite or silently renewed.
// The browser shares this signed token between tabs; the Worker remains authoritative.
const SESSION_SECONDS = 7 * 24 * 3600;
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
function configurationProblems(env) {
  // Expose binding NAMES and validation flags only; never return values, lengths, or secrets.
  const required=["ADMIN_ORIGIN","BACKEND_ORIGIN","GITHUB_CLIENT_ID","GITHUB_CLIENT_SECRET","SESSION_SIGNING_KEY","GITHUB_REPO_TOKEN","ALLOWED_GITHUB_USER_ID"];
  const missing=required.filter(k=>typeof env[k]!=="string" || env[k].length===0);
  const invalid=[];
  if(!missing.includes("ADMIN_ORIGIN") && !/^https:\/\//.test(env.ADMIN_ORIGIN)) invalid.push("ADMIN_ORIGIN_must_be_https");
  if(!missing.includes("BACKEND_ORIGIN") && !/^https:\/\//.test(env.BACKEND_ORIGIN)) invalid.push("BACKEND_ORIGIN_must_be_https");
  if(!missing.includes("SESSION_SIGNING_KEY") && env.SESSION_SIGNING_KEY.length < 32) invalid.push("SESSION_SIGNING_KEY_too_short");
  if(!missing.includes("ADMIN_ORIGIN") && !missing.includes("BACKEND_ORIGIN") && env.ADMIN_ORIGIN===env.BACKEND_ORIGIN) invalid.push("origins_must_differ");
  return {missing,invalid};
}
function configured(env) {
  const problems=configurationProblems(env);
  return problems.missing.length===0 && problems.invalid.length===0;
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
const FIRST_CAR_WORKFLOW = "/actions/workflows/first-car-dzen-collector.yml";
const FIRST_CAR_COOLDOWN_MS = 60 * 60_000;
const FIRST_CAR_EVENTS = new Set(["schedule", "workflow_dispatch"]);
const FIRST_CAR_QUEUE = "/contents/dzen/queue.json?ref=first-car-data";

async function firstCarQueue(env) {
  const snapshot = await githubJson(FIRST_CAR_QUEUE, env, {
    redirect:"manual", signal:AbortSignal.timeout(10_000), headers:{"cache-control":"no-cache"}
  });
  if (snapshot.status === 404) return {schema_version:1,articles:[]};
  if (snapshot.status !== 200) throw Error("First Car queue unavailable");
  const queue = decodeGitHubContent(snapshot.data);
  if (queue?.schema_version !== 1 || !Array.isArray(queue.articles)) throw Error("Invalid First Car queue");
  return queue;
}

async function firstCarTextSubmit(request, env, headers) {
  const active = firstCarTextArticle(env);
  if (!active || !env.FIRST_CAR_TEXT) return fail(503,"first_car_text_not_enabled",headers);
  const body = await ownerText(request);
  if (body.status !== 200) return fail(body.status,"invalid_article_text",headers);
  if (body.url !== active) return fail(404,"article_not_in_active_queue",headers);
  try {
    const queue = await firstCarQueue(env);
    const article = queue.articles.find(row => row?.url === body.url && row.source === "dzen_launcher_more");
    const published = Date.parse(article?.published_at);
    const now = Date.now();
    if (!(published <= now && now < published + DAY)) return fail(404,"article_not_in_active_queue",headers);
    const result = await privateText(env.FIRST_CAR_TEXT,"submit",{url:body.url,text:body.text,expires:published + DAY});
    if (!result.accepted) return fail(result.reason === "text_queue_full" ? 429 : 409,result.reason,headers);
    return send({ok:true},202,headers);
  } catch {
    return fail(502,"first_car_text_unavailable",headers);
  }
}

async function firstCarRun(request, url, env, headers) {
  if (!env.FIRST_CAR_ACTIONS_TOKEN) return fail(503,"first_car_not_enabled",headers);
  const actions = (path, options = {}, token = env.FIRST_CAR_ACTIONS_TOKEN) => githubJson(path, env, {
    ...options, redirect:"manual", signal:AbortSignal.timeout(10_000),
    headers:{...githubHeaders(token),...options.headers}
  });
  const describe = (run, state, report = null) => send({
    ok:true, id:run.id, state, conclusion:run.conclusion ?? null, report
  }, state === "started" ? 202 : 200, headers);
  let stage = "request";
  const failed = (error, kind, upstreamStatus) => {
    // Error messages, headers, redirect locations and response bodies may contain credentials.
    const diagnostic = {stage,kind};
    if (upstreamStatus !== undefined) diagnostic.upstream_status = upstreamStatus;
    console.warn("first_car_failure",diagnostic);
    return send({ok:false,error,...diagnostic},502,headers);
  };
  const upstreamFailed = (error,status) => failed(error,
    status >= 300 && status < 400 ? "upstream_3xx" : status !== 200 ? "upstream_http" : "invalid_response",status);
  try {
    if (request.method === "POST") {
      if (url.search) return fail(400,"unexpected_input",headers);
      // A body stream can be present even when the request contains zero bytes.
      for await (const chunk of request.body ?? []) {
        if (chunk.byteLength > 0) return fail(400,"unexpected_input",headers);
      }
      stage = "list_runs";
      const list = await actions(FIRST_CAR_WORKFLOW + "/runs?branch=main&per_page=10");
      if (list.status !== 200 || !Array.isArray(list.data?.workflow_runs)) return upstreamFailed("first_car_runs_unavailable",list.status);
      const runs = list.data.workflow_runs.filter(run => run.head_branch === "main" &&
        FIRST_CAR_EVENTS.has(run.event) && Number.isSafeInteger(run.id));
      const active = runs.find(run => run.status !== "completed");
      if (active) return describe(active,"running");
      const recent = runs.find(run => Date.now() - Date.parse(run.created_at) < FIRST_CAR_COOLDOWN_MS);
      if (recent) return describe(recent,"cooldown");
      stage = "dispatch";
      const dispatch = await actions(FIRST_CAR_WORKFLOW + "/dispatches", {
        method:"POST",headers:{"content-type":"application/json"},
        body:JSON.stringify({ref:"main",return_run_details:true})
      });
      const id = dispatch.data?.workflow_run_id;
      if (dispatch.status !== 200 || !Number.isSafeInteger(id) || id < 1) return upstreamFailed("first_car_dispatch_failed",dispatch.status);
      return describe({id},"started");
    }
    const id = Number(url.searchParams.get("run"));
    if (!/^\d+$/.test(url.searchParams.get("run") ?? "") || !Number.isSafeInteger(id) || id < 1) {
      return fail(400,"invalid_run",headers);
    }
    stage = "get_run";
    const {status,data:run} = await actions("/actions/runs/" + id);
    if (status !== 200 && status !== 404) return upstreamFailed("first_car_run_unavailable",status);
    if (status !== 200 || run?.id !== id || run.head_branch !== "main" || !FIRST_CAR_EVENTS.has(run.event) ||
        run.path?.split("@",1)[0] !== ".github/workflows/first-car-dzen-collector.yml") {
      return fail(404,"first_car_run_unavailable",headers);
    }
    if (run.status !== "completed") return describe(run,"running");
    stage = "read_report";
    const snapshot = await actions(FIRST_CAR_QUEUE,{},env.GITHUB_REPO_TOKEN);
    if (snapshot.status !== 200 && snapshot.status !== 404) return upstreamFailed("first_car_report_unavailable",snapshot.status);
    let report = null;
    if (snapshot.status === 200) {
      const last = decodeGitHubContent(snapshot.data).last_run;
      if (last?.id === id && [last.processed,last.errors,last.added].every(x => Number.isSafeInteger(x) && x >= 0)) {
        report = {processed:last.processed,errors:last.errors,added:last.added};
      }
    }
    return describe(run,"completed",report);
  } catch (error) {
    const name = error?.name;
    const kind = ["TypeError","TimeoutError","AbortError","SyntaxError"].includes(name) ? name : "unexpected_error";
    return failed("first_car_service_unavailable",kind);
  }
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



const COPY_FIELDS=["title","dzen_title","summary","article_markdown","threads_text","x_text","vk_title","vk_summary"];
const COPY_ROOT="editorial_inbox/auto_copyedits/";
const COPY_DECISIONS="editorial_inbox/auto_copyedit_decisions/";
const SHA40=/^[a-f0-9]{40}$/;
function validCopyReview(d){
  return !!d&&typeof d==="object"&&!Array.isArray(d)&&
    Object.keys(d).sort().join(",")==="action,article_id,candidate_sha,note,revision,source_sha,version"&&
    typeof d.article_id==="string"&&d.article_id.length<=80&&/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(d.article_id)&&
    Number.isSafeInteger(d.revision)&&d.revision>=1&&d.revision<9999&&
    Number.isSafeInteger(d.version)&&d.version>=1&&d.version<=5&&
    SHA40.test(d.candidate_sha)&&SHA40.test(d.source_sha)&&
    ["accept_copyedit","keep_original","revise_copyedit"].includes(d.action)&&
    typeof d.note==="string"&&d.note.length<=MAX_NOTE&&
    (d.action!=="revise_copyedit"||(d.version<5&&d.note.trim().length>0));
}
function copyTokens(value,re){
  return JSON.stringify(Array.from(value.matchAll(re),m=>m[0]).sort());
}
function validCopyPackage(draft,candidate,d){
  if(!draft||!candidate||draft.article_id!==d.article_id||draft.revision!==d.revision||
     draft.status!=="ready_for_review"||!Array.isArray(draft.editor_notes)||
     candidate.schema_version!==2||candidate.worker!=="hpii-chief-copyeditor"||
     candidate.article_id!==d.article_id||candidate.source_revision!==d.revision||
     candidate.copyedit_version!==d.version||candidate.source_draft_blob_sha!==d.source_sha||
     candidate.source_updated_at!==draft.updated_at||
     !["ready_for_comparison","no_change_recommended"].includes(candidate.status)||
     !Array.isArray(candidate.editor_flags)||candidate.editor_flags.length!==0)return false;
  const original=candidate.original_text,edited=candidate.edited_text;
  if(!original||!edited||[original,edited].some(x=>Object.keys(x).sort().join(",")!==COPY_FIELDS.slice().sort().join(",")))return false;
  for(const k of COPY_FIELDS){
    if(typeof original[k]!=="string"||original[k]!==draft.content?.[k]||
       typeof edited[k]!=="string"||!edited[k].trim()||edited[k].length>50000)return false;
    // Same conservative protection as the Python candidate validator.
    for(const re of [/\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?%?/g,/https?:\/\/[^\s\])>]+/g,/(?<![\p{L}\p{N}_])@[A-Za-z][\p{L}\p{N}_.]{1,30}/gu]){
      if(copyTokens(original[k],re)!==copyTokens(edited[k],re))return false;
    }
  }
  if(copyTokens(original.article_markdown,/^>\s.+$/gm)!==copyTokens(edited.article_markdown,/^>\s.+$/gm))return false;
  if(edited.title!==edited.dzen_title||Array.from(edited.threads_text).length>480||
     Array.from(edited.x_text).length>280||Array.from(edited.vk_title).length>200||
     Array.from(edited.vk_summary).length>350)return false;
  if(candidate.status==="no_change_recommended"&&COPY_FIELDS.some(k=>original[k]!==edited[k]))return false;
  if(candidate.status==="ready_for_comparison"&&original.article_markdown===edited.article_markdown)return false;
  if(d.action==="accept_copyedit"&&candidate.status!=="ready_for_comparison")return false;
  return true;
}
async function recordCopyReview(env,d,login){
  if(!validCopyReview(d))return fail(400,"invalid_copyedit_review");
  // Pin every read to one commit. Both draft and decision are saved in one
  // non-forced Git ref update; concurrent changes cause conflict, not overwrite.
  const ref="editorial-intake",head=await githubJson("/git/ref/heads/"+ref,env);
  const base=head.data?.object?.sha;
  if(head.status!==200||!SHA40.test(base))return fail(502,"copyedit_branch_unavailable");
  const at="?ref="+base,stem=d.article_id+"-r"+d.revision+"-v"+d.version;
  const [dr,cr,td,cd,listing,parent]=await Promise.all([
    githubJson("/contents/"+pathFor(d.article_id)+at,env),
    githubJson("/contents/"+COPY_ROOT+stem+".json"+at,env),
    githubJson("/contents/"+savedPath(d.article_id,d.revision)+at,env),
    githubJson("/contents/"+COPY_DECISIONS+stem+".json"+at,env),
    githubJson("/contents/"+COPY_ROOT.replace(/\/$/,"")+at,env),
    githubJson("/git/commits/"+base,env)
  ]);
  if(td.status===200||cd.status===200)return fail(409,"copyedit_decision_exists");
  if(td.status!==404||cd.status!==404||listing.status!==200||parent.status!==200)return fail(502,"copyedit_lookup_failed");
  if(dr.status!==200||cr.status!==200||dr.data.sha!==d.source_sha||cr.data.sha!==d.candidate_sha)return fail(409,"copyedit_source_changed");
  const prefix=d.article_id+"-r"+d.revision+"-v";
  if(!Array.isArray(listing.data)||listing.data.some(x=>x.name?.startsWith(prefix)&&Number(x.name.slice(prefix.length).replace(/\.json$/,""))>d.version))
    return fail(409,"copyedit_newer_candidate_exists");
  let draft,candidate;
  try{draft=decodeGitHubContent(dr.data);candidate=decodeGitHubContent(cr.data)}catch{return fail(409,"copyedit_invalid")}
  if(!validCopyPackage(draft,candidate,d))return fail(409,"copyedit_package_invalid");
  const treeBase=parent.data?.tree?.sha;
  if(!SHA40.test(treeBase))return fail(502,"copyedit_tree_unavailable");
  const now=new Date().toISOString(),accept=d.action==="accept_copyedit";
  const record={schema_version:1,article_id:d.article_id,source_revision:d.revision,copyedit_version:d.version,
    source_draft_blob_sha:d.source_sha,copyedit_blob_sha:d.candidate_sha,action:d.action,note:d.note.trim(),
    decided_by:login,decided_at:now,result_revision:accept?d.revision+1:d.revision,
    channel:"hpii-admin-oauth-gateway"};
  const path=COPY_DECISIONS+stem+".json";
  const tree=[{path,mode:"100644",type:"blob",content:JSON.stringify(record,null,2)+"\n"}];
  if(accept){
    const next={...draft,revision:d.revision+1,updated_at:now,
      content:{...draft.content,...candidate.edited_text},
      editor_notes:[...draft.editor_notes,"copyedit_accepted="+stem+".json; copyedit_sha="+d.candidate_sha]};
    tree.push({path:pathFor(d.article_id),mode:"100644",type:"blob",content:JSON.stringify(next,null,2)+"\n"});
  }
  const post=(p,body)=>githubJson(p,env,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(body)});
  const tr=await post("/git/trees",{base_tree:treeBase,tree});
  if(tr.status!==201||!SHA40.test(tr.data?.sha))return fail(502,"copyedit_tree_write_failed");
  const commit=await post("/git/commits",{message:"review(auto-copyeditor): "+stem+" "+d.action,tree:tr.data.sha,parents:[base]});
  if(commit.status!==201||!SHA40.test(commit.data?.sha))return fail(502,"copyedit_commit_failed");
  const write=await githubJson("/git/refs/heads/"+ref,env,{method:"PATCH",headers:{"content-type":"application/json"},body:JSON.stringify({sha:commit.data.sha,force:false})});
  if(write.status!==200||write.data?.object?.sha!==commit.data.sha)
    return fail([409,422].includes(write.status)?409:502,"copyedit_ref_conflict_or_write_failed");
  return send({ok:true,status:accept?"copyedit_applied":d.action==="keep_original"?"original_retained":"copyedit_revision_requested",
    article_id:d.article_id,revision:record.result_revision,verification_path:path,commit_sha:commit.data.sha});
}

function validCoverReview(d) {
  if (!d || typeof d!=="object" || Array.isArray(d)) return false;
  if (JSON.stringify(Object.keys(d).sort())!==
      JSON.stringify(["article_id","revision","text_updated_at","cover_version","image_blob_sha","action","note"].sort())) return false;
  return typeof d.article_id==="string" && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(d.article_id) && d.article_id.length<=80 &&
    Number.isSafeInteger(d.revision) && d.revision>=1 && d.revision<=9999 &&
    Number.isSafeInteger(d.cover_version) && d.cover_version>=1 && d.cover_version<=5 &&
    typeof d.text_updated_at==="string" && d.text_updated_at.length>0 && d.text_updated_at.length<80 &&
    typeof d.image_blob_sha==="string" && /^[0-9a-f]{40}$/.test(d.image_blob_sha) &&
    ["approve_cover","revise_cover"].includes(d.action) &&
    typeof d.note==="string" && d.note.length<=MAX_NOTE &&
    (d.action!=="revise_cover" || d.note.trim().length>0);
}

async function recordCoverReview(env, data, login) {
  if(!validCoverReview(data))return fail(400,"invalid_cover_review");
  const ref="editorial-intake",stem=data.article_id+"-r"+data.revision+"-v"+data.cover_version;
  const location="editorial_inbox/auto_cover_decisions/"+stem+".json";
  const draftPath=pathFor(data.article_id), textPath=savedPath(data.article_id,data.revision);
  const coverPath="editorial_inbox/auto_covers/"+stem+".json";
  const imagePath="editorial_inbox/auto_covers/"+stem+".webp";
  const [draft,text,cover,image,old]=await Promise.all([
    githubJson("/contents/"+draftPath+"?ref="+ref,env),
    githubJson("/contents/"+textPath+"?ref="+ref,env),
    githubJson("/contents/"+coverPath+"?ref="+ref,env),
    githubJson("/contents/"+imagePath+"?ref="+ref,env),
    githubJson("/contents/"+location+"?ref="+ref,env)
  ]);
  if(old.status===200)return fail(409,"cover_review_already_exists");
  if(old.status!==404)return fail(502,"cover_review_lookup_failed");
  if(data.cover_version>1){
    const previous="editorial_inbox/auto_cover_decisions/"+data.article_id+"-r"+data.revision+"-v"+(data.cover_version-1)+".json";
    const prior=await githubJson("/contents/"+previous+"?ref="+ref,env);
    if(prior.status!==200)return fail(409,"previous_cover_revision_missing");
    let pv;
    try{pv=decodeGitHubContent(prior.data)}catch{return fail(409,"previous_cover_revision_invalid")}
    if(pv.article_id!==data.article_id||pv.text_revision!==data.revision||
       pv.text_updated_at!==data.text_updated_at||pv.cover_version!==data.cover_version-1||
       pv.action!=="revise_cover"||pv.status!=="cover_revision_requested"||!pv.note?.trim())
      return fail(409,"previous_cover_revision_not_requested");
  }
  if([draft,cover,image].some(x=>x.status!==200)||![200,404].includes(text.status))return fail(409,"cover_or_approval_unavailable");
  let dv,tv=null,cv;
  try{dv=decodeGitHubContent(draft.data);if(text.status===200)tv=decodeGitHubContent(text.data);cv=decodeGitHubContent(cover.data)}
  catch{return fail(409,"cover_or_approval_invalid")}
  const textSha=tv?text.data.sha:null;
  if(tv&&(tv.article_id!==data.article_id||tv.revision!==data.revision||tv.updated_at!==data.text_updated_at||
      tv.status!=="text_approved_cover_pending"||tv.action!=="approve_text"||tv.draft_blob_sha!==draft.data.sha))
    return fail(409,"text_revision_or_approval_changed");
  if(dv.article_id!==data.article_id||dv.revision!==data.revision||dv.updated_at!==data.text_updated_at||
     dv.status!=="ready_for_review"||
     cv.schema_version!==1||cv.article_id!==data.article_id||cv.text_revision!==data.revision||
     cv.text_updated_at!==data.text_updated_at||cv.status!=="ready_for_cover_review"||
     cv.source_draft_blob_sha!==draft.data.sha||
     (cv.source_decision_blob_sha!==null&&(!textSha||cv.source_decision_blob_sha!==textSha))||
     cv.image_path!==imagePath||cv.image_blob_sha!==data.image_blob_sha||
     image.data.sha!==data.image_blob_sha||
     !Number.isSafeInteger(cv.width)||!Number.isSafeInteger(cv.height)||
     Math.abs(cv.width/cv.height-16/9)>0.02)
    return fail(409,"cover_or_text_changed");
  const status=data.action==="approve_cover"?"cover_approved_handoff_pending":"cover_revision_requested";
  const record={
    schema_version:1,article_id:data.article_id,text_revision:data.revision,
    text_updated_at:data.text_updated_at,cover_version:data.cover_version,
    cover_blob_sha:image.data.sha,cover_metadata_blob_sha:cover.data.sha,
    source_draft_blob_sha:draft.data.sha,source_text_decision_blob_sha:textSha,
    action:data.action,note:data.note.trim(),status,decided_by:login,
    decided_at:new Date().toISOString(),channel:"hpii-admin-oauth-gateway"
  };
  const result=await githubJson("/contents/"+location,env,{
    method:"PUT",headers:{"content-type":"application/json"},
    body:JSON.stringify({branch:ref,message:"review(auto-cover): "+data.article_id+" r"+data.revision+" v"+data.cover_version,
      content:encodeGitHubContent(record)})
  });
  if(![200,201].includes(result.status))return fail([409,422].includes(result.status)?409:502,"cover_review_write_failed");
  return send({ok:true,status,article_id:data.article_id,revision:data.revision,
    cover_version:data.cover_version,verification_path:location,commit_sha:result.data.commit?.sha||null,
    note:"No publication or site queue changes made."});
}

// The image intake only accepts manually selected, version-locked WebP candidates.
// It cannot approve a cover or publish a story.
function webpDimensions(data) {
  if (data.length<1024 || data.length>800_000) throw Error("image_size_invalid");
  const four=(offset)=>String.fromCharCode(...data.slice(offset,offset+4));
  if (four(0)!=="RIFF" || four(8)!=="WEBP") throw Error("not_webp");
  const v=new DataView(data.buffer,data.byteOffset,data.byteLength);
  if (v.getUint32(4,true)+8!==data.length) throw Error("webp_riff_size_invalid");
  const tag=four(12),chunkSize=v.getUint32(16,true);
  if (20+chunkSize>data.length || chunkSize<10) throw Error("webp_chunk_invalid");
  let width,height;
  if(tag==="VP8X") {
    width=1+data[24]+(data[25]<<8)+(data[26]<<16);
    height=1+data[27]+(data[28]<<8)+(data[29]<<16);
  } else if(tag==="VP8L") {
    if(data[20]!==0x2f)throw Error("webp_lossless_signature_invalid");
    width=1+data[21]+((data[22]&0x3f)<<8);
    height=1+(data[22]>>6)+(data[23]<<2)+((data[24]&0xf)<<10);
  } else if(tag==="VP8 ") {
    if(data[23]!==0x9d||data[24]!==0x01||data[25]!==0x2a)throw Error("webp_lossy_signature_invalid");
    width=v.getUint16(26,true)&0x3fff;
    height=v.getUint16(28,true)&0x3fff;
  } else throw Error("webp_chunk_type_invalid");
  if(width<640 || height<360 || width>4096 || height>2304 || Math.abs(width/height-16/9)>0.02)
    throw Error("webp_dimensions_invalid");
  return {width,height};
}
function encodeBinaryToBase64(bytes) {
  let all="";
  for(let i=0;i<bytes.length;i+=16000)all+=String.fromCharCode(...bytes.subarray(i,i+16000));
  return btoa(all);
}
async function blobSha(bytes) {
  const prefix=enc.encode("blob "+bytes.length+"\u0000");
  const payload=new Uint8Array(prefix.length+bytes.length);
  payload.set(prefix);payload.set(bytes,prefix.length);
  const digest=new Uint8Array(await crypto.subtle.digest("SHA-1",payload));
  return Array.from(digest,x=>x.toString(16).padStart(2,"0")).join("");
}
async function receiveCover(env, request, login) {
  if(Number(request.headers.get("content-length")||0)>900_000) return fail(413,"image_too_large");
  if(!(request.headers.get("content-type")||"").startsWith("multipart/form-data;")) return fail(415,"form_data_required");
  let data;
  try{data=await request.formData()}catch{return fail(400,"bad_upload_form")}
  const article_id=data.get("article_id"), revision=Number(data.get("revision")),
        cover_version=Number(data.get("cover_version")||1),
        updated_at=data.get("updated_at"), headline=data.get("headline"), concept=data.get("concept"),
        file=data.get("file");
  if(typeof article_id!=="string" || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(article_id) || article_id.length>80 ||
     !Number.isSafeInteger(revision)||revision<1||revision>9999||
     !Number.isSafeInteger(cover_version)||cover_version<1||cover_version>5||
     typeof updated_at!=="string"||updated_at.length>80||
     typeof headline!=="string"||headline.trim().length<2||headline.length>100||
     typeof concept!=="string"||concept.trim().length<8||concept.length>600||
     !file || typeof file.arrayBuffer!=="function"||file.size<1024||file.size>800_000||
     !/\.webp$/i.test(file.name||""))return fail(400,"invalid_cover_upload");
  const raw=new Uint8Array(await file.arrayBuffer());
  let size;
  try{size=webpDimensions(raw)}catch(e){return fail(400,e.message||"invalid_webp")}
  const ref="editorial-intake";
  const draft=await githubJson("/contents/"+pathFor(article_id)+"?ref="+ref,env);
  const decision=await githubJson("/contents/"+savedPath(article_id,revision)+"?ref="+ref,env);
  if(draft.status!==200||![200,404].includes(decision.status))return fail(409,"approved_text_unavailable");
  let body,approve=null;
  try{body=decodeGitHubContent(draft.data);if(decision.status===200)approve=decodeGitHubContent(decision.data)}catch{return fail(409,"approval_invalid")}
  if(body.article_id!==article_id||body.revision!==revision||body.updated_at!==updated_at||
     body.status!=="ready_for_review"||(approve&&(approve.article_id!==article_id||approve.revision!==revision||
     approve.updated_at!==updated_at||approve.action!=="approve_text"||
     approve.status!=="text_approved_cover_pending"||approve.draft_blob_sha!==draft.data.sha)))
    return fail(409,"text_revision_or_approval_changed");
  if(cover_version>1){
    const previous="editorial_inbox/auto_cover_decisions/"+article_id+"-r"+revision+"-v"+(cover_version-1)+".json";
    const prior=await githubJson("/contents/"+previous+"?ref="+ref,env);
    if(prior.status!==200)return fail(409,"previous_cover_revision_missing");
    let pv;
    try{pv=decodeGitHubContent(prior.data)}catch{return fail(409,"previous_cover_revision_invalid")}
    if(pv.article_id!==article_id||pv.text_revision!==revision||pv.text_updated_at!==updated_at||
       pv.cover_version!==cover_version-1||pv.action!=="revise_cover"||
       pv.status!=="cover_revision_requested"||!pv.note?.trim())
      return fail(409,"previous_cover_revision_not_requested");
  }
  const stem=article_id+"-r"+revision+"-v"+cover_version;
  const image_path="editorial_inbox/auto_covers/"+stem+".webp";
  const meta_path="editorial_inbox/auto_covers/"+stem+".json";
  const exists=await githubJson("/contents/"+meta_path+"?ref="+ref,env);
  if(exists.status===200)return fail(409,"cover_candidate_exists");
  if(exists.status!==404)return fail(502,"cover_lookup_failed");
  let sha;
  try{sha=await blobSha(raw)}catch{return fail(500,"image_hash_unavailable")}
  const existingImage=await githubJson("/contents/"+image_path+"?ref="+ref,env);
  if(existingImage.status===200){
    if(existingImage.data.sha!==sha)return fail(409,"cover_image_already_exists");
  }else if(existingImage.status===404){
    const upload=await githubJson("/contents/"+image_path,env,{
      method:"PUT",headers:{"content-type":"application/json"},
      body:JSON.stringify({branch:ref,message:"cover(auto-editor): stage WebP "+article_id+" r"+revision,
        content:encodeBinaryToBase64(raw)})
    });
    if(![200,201].includes(upload.status))return fail(upload.status===409||upload.status===422?409:502,"image_write_failed");
    if(upload.data.content?.sha!==sha)return fail(502,"image_sha_unverified");
  }else return fail(502,"cover_image_lookup_failed");
  const meta={
    schema_version:1,article_id,text_revision:revision,text_updated_at:updated_at,
    source_draft_blob_sha:draft.data.sha,source_decision_blob_sha:approve?decision.data.sha:null,
    status:"ready_for_cover_review",image_path,image_blob_sha:sha,
    width:size.width,height:size.height,concept:concept.trim(),headline:headline.trim(),
    artist_notes:"Загружено вручную через защищённую админку; требуется просмотр главреда. Загрузил "+login+".",
    created_at:new Date().toISOString()
  };
  const written=await githubJson("/contents/"+meta_path,env,{
    method:"PUT",headers:{"content-type":"application/json"},
    body:JSON.stringify({branch:ref,message:"cover(auto-editor): register review candidate "+article_id+" r"+revision,
       content:encodeGitHubContent(meta)})
  });
  if(![200,201].includes(written.status))return fail(written.status===409||written.status===422?409:502,"cover_metadata_write_failed");
  const readback=await githubJson("/contents/"+meta_path+"?ref="+ref,env);
  if(readback.status!==200)return fail(502,"cover_metadata_unverified");
  let verified;
  try{verified=decodeGitHubContent(readback.data)}catch{return fail(502,"cover_metadata_unverified")}
  if(verified.image_blob_sha!==sha||verified.status!=="ready_for_cover_review"||verified.source_draft_blob_sha!==draft.data.sha)
    return fail(502,"cover_metadata_mismatch");
  return send({ok:true,status:"ready_for_cover_review",article_id,revision,
    image_path,metadata_path:meta_path,width:size.width,height:size.height,image_blob_sha:sha,
    note:"Candidate only. Not approved or published."});
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

// Return only a GitHub-defined failure CATEGORY; never forward error descriptions,
// OAuth codes, responses, secrets, credentials or user-provided strings.
const GITHUB_OAUTH_ERRORS=new Set([
  "incorrect_client_credentials","bad_verification_code","redirect_uri_mismatch",
  "unverified_user_email","slow_down","application_suspended","access_denied",
  "invalid_request","invalid_grant"
]);
function oauthExchangeFailure(env,reason) {
  const safe=GITHUB_OAUTH_ERRORS.has(reason)?reason:"unknown_exchange_error";
  const label={
    incorrect_client_credentials:"GitHub не принял настройки OAuth-приложения.",
    bad_verification_code:"Временный код входа недействителен или уже использован.",
    redirect_uri_mismatch:"Адрес возврата не совпал с настройками приложения GitHub.",
    unverified_user_email:"GitHub требует подтвердить электронную почту учётной записи.",
    slow_down:"GitHub временно ограничил частые попытки входа.",
    application_suspended:"GitHub приостановил OAuth-приложение.",
    access_denied:"Вход был отменён или не разрешён.",
    invalid_request:"GitHub отклонил параметры запроса.",
    invalid_grant:"GitHub отклонил временный код.",
    unknown_exchange_error:"GitHub не выдал подтверждение входа."
  }[safe];
  const nonce=random();
  const payload=JSON.stringify({type:"hpii-auth-error",reason:safe,backend:env.BACKEND_ORIGIN});
  const html='<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+
    '<title>ХПИИ — ошибка входа</title><style>body{font:16px/1.55 system-ui,sans-serif;background:#f5f2eb;color:#18313b;margin:0;padding:24px}'+
    'main{max-width:560px;margin:8vh auto;padding:26px;background:white;border:1px solid #d5dedc;border-radius:16px}h1{font-size:24px}'+
    'code{overflow-wrap:anywhere;background:#edf0ed;padding:4px 8px;border-radius:5px}a{color:#0f746a}</style></head><body><main>'+
    '<h1>Не удалось войти через GitHub</h1><p>'+label+'</p>'+
    '<p>Код ошибки: <code>'+safe+'</code></p>'+
    '<p>Закрой эту вкладку, вернись в админку и запусти <strong>новую попытку входа</strong>. Старую ссылку авторизации повторно не открывай.</p>'+
    '<p>Если ошибка повторится, сообщи нам только код ошибки — токены и ключи присылать не нужно.</p>'+
    '<p><a href="'+env.ADMIN_ORIGIN+'/admin/">Вернуться к админке</a></p></main>'+
    '<script nonce="'+nonce+'">if(window.opener){window.opener.postMessage('+payload+','+JSON.stringify(env.ADMIN_ORIGIN)+')}</script></body></html>';
  return new Response(html,{status:401,headers:{...noStore,"content-type":"text/html; charset=utf-8",
    "content-security-policy":"default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-"+nonce+"'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "set-cookie":dropCookie}});
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
  if (!exchange.ok || !tokens.access_token) return oauthExchangeFailure(env,tokens.error);
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
  // No OAuth/GitHub access token reaches the browser. A seven-day, fixed-expiry
  // HMAC session arrives only by origin-bound popup messaging.
  const html='<!doctype html><meta charset="utf-8"><title>ХПИИ — вход</title>'+
    '<p>Вход подтверждён. Окно можно закрыть.</p>'+
    '<script nonce="'+nonce+'">if(window.opener){window.opener.postMessage('+JSON.stringify({type:"hpii-auth",token,login:user.login,backend:env.BACKEND_ORIGIN})+','+JSON.stringify(env.ADMIN_ORIGIN)+');window.close()}</script>';
  return new Response(html,{status:200,headers:{...noStore,"content-type":"text/html; charset=utf-8",
    "content-security-policy":"default-src 'none'; script-src 'nonce-"+nonce+"'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "set-cookie":dropCookie}});
}

const DOSSIER_PATH="/contents/data/dossier.json";
const DOSSIER_ID=/^[a-z0-9]+(?:-[a-z0-9]+)*$/;
function validDossierId(id){return typeof id==="string"&&id.length<=72&&DOSSIER_ID.test(id)}
function validDossierConfig(config){
  return config&&Object.keys(config).sort().join(",")==="items,schema_version"&&config.schema_version===1&&
    Array.isArray(config.items)&&config.items.length<=500&&config.items.every(validDossierId)&&
    new Set(config.items).size===config.items.length;
}
function validDossierAction(d){
  return d&&Object.keys(d).sort().join(",")==="action,article_id,config_sha"&&
    validDossierId(d.article_id)&&["add","remove"].includes(d.action)&&typeof d.config_sha==="string"&&SHA40.test(d.config_sha);
}
async function dossierRead(env){
  const head=await githubJson("/git/ref/heads/main",env);
  const sha=head.data?.object?.sha;
  if(head.status!==200||!SHA40.test(sha))throw Error("dossier_head_unavailable");
  const [cfg,news]=await Promise.all([githubJson(DOSSIER_PATH+"?ref="+sha,env),githubJson("/contents/news.json?ref="+sha,env)]);
  if(cfg.status!==200||news.status!==200||!SHA40.test(cfg.data?.sha))throw Error("dossier_catalog_unavailable");
  const config=decodeGitHubContent(cfg.data),rows=decodeGitHubContent(news.data);
  if(!validDossierConfig(config)||!Array.isArray(rows))throw Error("dossier_config_invalid");
  const published=rows.filter(r=>validDossierId(r.id)&&r.url==="articles/"+r.id+"/"&&typeof r.title==="string"&&
    typeof r.cover==="string"&&/^assets\/[a-z0-9][a-z0-9/_-]*\.(webp|png|jpe?g)$/.test(r.cover))
    .map(r=>({id:r.id,title:r.title,published:r.published,published_at_utc:r.published_at_utc,rubric:r.rubric}));
  if(config.items.some(id=>!published.some(r=>r.id===id)))throw Error("dossier_member_not_published");
  return {config,config_sha:cfg.data.sha,published,head:sha};
}
async function dossierAction(env,body,headers){
  if(!validDossierAction(body))return fail(400,"invalid_dossier_action",headers);
  try{
    const state=await dossierRead(env);
    if(state.config_sha!==body.config_sha)return fail(409,"dossier_config_changed",headers);
    if(!state.published.some(r=>r.id===body.article_id))return fail(400,"dossier_article_not_published",headers);
    const exists=state.config.items.includes(body.article_id);
    if((body.action==="add"&&exists)||(body.action==="remove"&&!exists))
      return send({ok:true,status:"unchanged",items:state.config.items,config_sha:state.config_sha},200,headers);
    const items=body.action==="add"?[body.article_id,...state.config.items]:state.config.items.filter(id=>id!==body.article_id);
    const next={schema_version:1,items};
    if(!validDossierConfig(next))return fail(400,"dossier_limit",headers);
    // Compare-and-swap of the exact config blob; no article/queue/approval writes.
    const write=await githubJson(DOSSIER_PATH,env,{method:"PUT",headers:{"content-type":"application/json"},
      body:JSON.stringify({branch:"main",sha:state.config_sha,message:"dossier: "+body.action+" "+body.article_id,
        content:encodeGitHubContent(next)})});
    if(write.status!==200||!SHA40.test(write.data?.commit?.sha)||!SHA40.test(write.data?.content?.sha))
      return fail([409,422].includes(write.status)?409:502,"dossier_write_conflict_or_failed",headers);
    return send({ok:true,status:"saved_pending_site_refresh",items,config_sha:write.data.content.sha,commit_sha:write.data.commit.sha},200,headers);
  }catch{return fail(502,"dossier_catalog_unavailable",headers)}
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
    if (!configured(env)) {
      const problems=configurationProblems(env);
      return send({ok:false,error:"gateway_not_configured",missing:problems.missing,invalid:problems.invalid},503);
    }
    if (url.origin!==env.BACKEND_ORIGIN) return fail(403,"unexpected_host");
    if (url.pathname==="/auth/start" && request.method==="GET") return login(env);
    if (url.pathname==="/auth/callback" && request.method==="GET") return callback(request,env);
    if (url.pathname==="/health" && request.method==="GET") return send({
      ok:true,service:"hpii-auth-gateway",cover_review_max_version:5,parallel_cover_review:true,copyedit_review:true,dossier_management:true,
      first_car_text_binding:Boolean(env.FIRST_CAR_TEXT),
      first_car_text_active:Boolean(env.FIRST_CAR_TEXT && firstCarTextArticle(env)),
    });
    if (url.pathname==="/api/first-car/workflow-text" && request.method==="GET") {
      if (url.search) return fail(400,"unexpected_input");
      if (!await firstCarWorkflowIdentity(request)) return fail(401,"workflow_identity_required");
      const active = firstCarTextArticle(env);
      if (!active) return send({ok:true,texts:{}});
      if (!env.FIRST_CAR_TEXT) return fail(503,"first_car_text_not_enabled");
      try {
        const texts = await privateText(env.FIRST_CAR_TEXT,"texts");
        return send({ok:true,texts:typeof texts[active] === "string" ? {[active]:texts[active]} : {}});
      } catch {
        return fail(502,"first_car_text_unavailable");
      }
    }
    if (url.pathname.startsWith("/api/")) {
      if (!origin(request,env)) return fail(403,"origin_not_allowed");
      if (request.method==="OPTIONS") return new Response(null,{status:204,headers:{...noStore,...cors(env)}});
      const headers=cors(env);
      const session=await verifySession(request,env);
      if (!session) return fail(401,"login_required",headers);
      if (url.pathname==="/api/session" && request.method==="GET") {
        return send({ok:true,login:session.login,exp:session.exp},200,headers);
      }
      if(url.pathname==="/api/dossier"&&request.method==="GET"){
        if(url.search)return fail(400,"unexpected_input",headers);
        try{const state=await dossierRead(env);return send({ok:true,...state},200,headers)}
        catch{return fail(502,"dossier_catalog_unavailable",headers)}
      }
      if(url.pathname==="/api/dossier"&&request.method==="POST"){
        if(url.search)return fail(400,"unexpected_input",headers);
        if((request.headers.get("content-type")||"").split(";")[0].trim()!=="application/json")return fail(415,"json_required",headers);
        const raw=await request.text();
        if(raw.length>2000)return fail(413,"request_too_large",headers);
        let data;try{data=JSON.parse(raw)}catch{return fail(400,"bad_json",headers)}
        return dossierAction(env,data,headers);
      }
      if (url.pathname==="/api/first-car/collect" && ["GET","POST"].includes(request.method)) {
        return firstCarRun(request,url,env,headers);
      }
      if (url.pathname==="/api/first-car/queue" && request.method==="GET") {
        if (url.search) return fail(400,"unexpected_input",headers);
        try {
          const textArticle = firstCarTextArticle(env);
          const [queue,pending] = await Promise.all([
            firstCarQueue(env),
            textArticle && env.FIRST_CAR_TEXT ? privateText(env.FIRST_CAR_TEXT,"pending").catch(() => null) : null,
          ]);
          return send({ok:true,queue,now:Date.now(),
            text_article:Array.isArray(pending) ? textArticle : null,
            pending:Array.isArray(pending) ? pending.filter(item => item === textArticle) : null,
          },200,headers);
        } catch {
          return fail(502,"first_car_queue_unavailable",headers);
        }
      }
      if (url.pathname==="/api/first-car/text" && request.method==="POST") {
        if (url.search) return fail(400,"unexpected_input",headers);
        return firstCarTextSubmit(request,env,headers);
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
      if(url.pathname==="/api/copyedit-review" && request.method==="POST"){
        if((request.headers.get("content-type")||"").split(";")[0].trim()!=="application/json")return fail(415,"json_required",headers);
        const raw=await request.text();
        if(raw.length>8000)return fail(413,"request_too_large",headers);
        let data;
        try{data=JSON.parse(raw)}catch{return fail(400,"bad_json",headers)}
        const result=await recordCopyReview(env,data,session.login);
        const merged=new Headers(result.headers);
        Object.entries(headers).forEach(([k,v])=>merged.set(k,v));
        return new Response(result.body,{status:result.status,headers:merged});
      }
      if(url.pathname==="/api/cover-review" && request.method==="POST"){
        if((request.headers.get("content-type")||"").split(";")[0].trim()!=="application/json")
          return fail(415,"json_required",headers);
        const raw=await request.text();
        if(raw.length>8000)return fail(413,"request_too_large",headers);
        let data;
        try{data=JSON.parse(raw)}catch{return fail(400,"bad_json",headers)}
        const result=await recordCoverReview(env,data,session.login);
        const merged=new Headers(result.headers);
        Object.entries(headers).forEach(([k,v])=>merged.set(k,v));
        return new Response(result.body,{status:result.status,headers:merged});
      }
      if(url.pathname==="/api/cover-upload" && request.method==="POST"){
        const result=await receiveCover(env,request,session.login);
        const resultHeaders=new Headers(result.headers);
        Object.entries(headers).forEach(([k,v])=>resultHeaders.set(k,v));
        return new Response(result.body,{status:result.status,headers:resultHeaders});
      }
      return fail(404,"route_not_found",headers);
    }
    return fail(404,"route_not_found");
  }
};
// Test-friendly pure validation exports; no secrets.
export const __test = {validReview,validCoverReview,validCopyReview,validCopyPackage,webpDimensions,validDossierConfig,validDossierAction};
