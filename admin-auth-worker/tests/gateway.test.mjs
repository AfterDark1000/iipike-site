import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto,createHash,createHmac} from "node:crypto";
import gateway, {__test} from "../src/index.mjs";
globalThis.crypto ||= webcrypto;

const env={
  ADMIN_ORIGIN:"https://iipike.ru",
  BACKEND_ORIGIN:"https://hpii-auth.example.workers.dev",
  GITHUB_CLIENT_ID:"fake-client",
  GITHUB_CLIENT_SECRET:"fake-client-secret",
  SESSION_SIGNING_KEY:"testing-only-secret-which-is-much-longer-than-32",
  GITHUB_REPO_TOKEN:"fake-repo-token",
  ALLOWED_GITHUB_USER_ID:"284211090"
};
function call(path, opts={}) {
  return gateway.fetch(new Request(env.BACKEND_ORIGIN+path,opts),env);
}
function exampleReview() {
  return {article_id:"test-carbon-story",revision:4,
    updated_at:"2026-11-17T09:14:28.326Z",action:"revise",note:"Move paragraph"};
}
test("validation rejects unexpected fields and bad actions",()=>{
  assert.equal(__test.validReview(exampleReview()),true);
  assert.equal(__test.validReview({...exampleReview(),article_id:"../bad"}),false);
  assert.equal(__test.validReview({...exampleReview(),status:"editor_approved"}),false);
  assert.equal(__test.validReview({...exampleReview(),action:"publish"}),false);
  assert.equal(__test.validReview({...exampleReview(),note:""}),false);
});
test("fail closed before login",async()=>{
  let r=await call("/api/session",{headers:{Origin:env.ADMIN_ORIGIN}});
  assert.equal(r.status,401);
  r=await call("/api/session",{headers:{Origin:"https://attacker.example"}});
  assert.equal(r.status,403);
  r=await call("/health");
  assert.equal(r.status,200);
  assert.equal((await r.json()).cover_review_max_version,5);
});
function firstCarSession(bindings={}) {
  const enabled={...env,FIRST_CAR_ACTIONS_TOKEN:"fixture-actions-token",...bindings};
  const raw=Buffer.from(JSON.stringify({kind:"session",user_id:284211090,login:"AfterDark1000",
    exp:Math.floor(Date.now()/1000)+600})).toString("base64url");
  const mac=createHmac("sha256",env.SESSION_SIGNING_KEY).update(raw).digest("base64url");
  const session={Origin:env.ADMIN_ORIGIN,Authorization:`Bearer ${raw}.${mac}`};
  const request=(path,options={})=>gateway.fetch(new Request(env.BACKEND_ORIGIN+path,{headers:session,...options}),enabled);
  return {enabled,session,request};
}
test("First Car queue reads the canonical data branch, reports upstream errors, and requires the owner",async(t)=>{
  const {request}=firstCarSession();
  const route="/api/first-car/queue";
  const queue={schema_version:1,articles:[{url:"https://dzen.ru/a/avwsiGM1tFu-0T5x"}]};
  let status=200;
  const github=t.mock.method(globalThis,"fetch",async(input,options)=>{
    assert.equal(String(input),"https://api.github.com/repos/AfterDark1000/iipike-site/contents/dzen/queue.json?ref=first-car-data");
    assert.equal(options.redirect,"manual");
    return Response.json({type:"file",sha:"queue-sha",content:Buffer.from(JSON.stringify(queue)).toString("base64")},{status});
  });
  assert.equal((await request(route,{headers:{Origin:env.ADMIN_ORIGIN}})).status,401);
  assert.equal((await request(route+"?ref=other")).status,400);
  assert.equal(github.mock.callCount(),0);
  const response=await request(route);
  assert.equal(response.headers.get("cache-control"),"no-store");
  const snapshot=await response.json();
  assert.deepEqual(snapshot.queue,queue);
  assert.ok(Math.abs(snapshot.now-Date.now())<5000);
  status=503;
  assert.equal((await request(route)).status,502);
  status=404;
  assert.deepEqual((await (await request(route)).json()).queue,{schema_version:1,articles:[]});
});
test("First Car text intake accepts only owner text tied to a known fresh publication and never echoes it",async(t)=>{
  const canonical="https://dzen.ru/a/avwsiGM1tFu-0T5x";
  const expired="https://dzen.ru/a/aul8OQIrtEtCeO6V";
  const body="Содержательный текст статьи об эксперименте. ".repeat(10).trim();
  const saved=[];
  const {request,session,enabled}=firstCarSession({FIRST_CAR_OWNER_TEXT_ARTICLE_ID:canonical.split("/").at(-1),FIRST_CAR_TEXT:{
    idFromName: name => name,
    get: () => ({fetch: async (path,opts) => {
      if (path.endsWith("/submit")) {
        saved.push(JSON.parse(opts.body));
        return Response.json({accepted:true});
      }
      assert.ok(path.endsWith("/pending"));
      return Response.json([...saved.map(item => item.url),expired]);
    }})
  }});
  const post=(data,headers=session)=>request("/api/first-car/text",{
    method:"POST", headers:{...headers,"content-type":"application/json"},body:JSON.stringify(data)
  });
  const published=Date.now()-3600_000;
  const queue={schema_version:1,articles:[
    {url:canonical,source:"dzen_launcher_more",published_at:new Date(published).toISOString()},
    {url:expired,source:"dzen_launcher_more",published_at:new Date(published-86400_000).toISOString()},
  ]};
  const github=t.mock.method(globalThis,"fetch",async(input)=>{
    assert.ok(String(input).endsWith("/contents/dzen/queue.json?ref=first-car-data"));
    return Response.json({type:"file",sha:"queue-sha",content:Buffer.from(JSON.stringify(queue)).toString("base64")});
  });
  assert.equal((await post({url:canonical,text:body},{Origin:env.ADMIN_ORIGIN})).status,401);
  assert.equal((await post({url:canonical,text:body},{...session,Origin:"https://wrong.test"})).status,403);
  assert.equal((await post({url:canonical,text:"Заголовок"})).status,400);
  assert.equal((await post({url:canonical,text:body,override:true})).status,400);
  assert.equal((await post({url:canonical,text:"a".repeat(160_001)})).status,413);
  assert.equal(github.mock.callCount(),0);
  enabled.FIRST_CAR_OWNER_TEXT_ARTICLE_ID=expired.split("/").at(-1);
  assert.equal((await post({url:expired,text:body})).status,404);
  enabled.FIRST_CAR_OWNER_TEXT_ARTICLE_ID=canonical.split("/").at(-1);
  assert.equal((await post({url:"https://dzen.ru/a/unknown-publication",text:body})).status,404);
  const accepted=await post({url:canonical,text:body});
  assert.equal(accepted.status,202);
  assert.deepEqual(await accepted.json(),{ok:true});
  assert.deepEqual(saved,[{url:canonical,text:body,expires:published+86400_000}]);
  const status=await (await request("/api/first-car/queue")).json();
  assert.deepEqual(status.pending,[canonical]);
  assert.equal(status.text_article,canonical);
  assert.ok(!JSON.stringify(status).includes(body));
  delete enabled.FIRST_CAR_OWNER_TEXT_ARTICLE_ID;
  assert.equal((await post({url:canonical,text:body})).status,503);
  assert.equal((await (await request("/health")).json()).first_car_text_active,false);
  enabled.FIRST_CAR_OWNER_TEXT_ARTICLE_ID=canonical.split("/").at(-1);
  enabled.FIRST_CAR_TEXT={idFromName: name=>name,get:()=>({fetch:()=>{throw Error("fake outage")}})};
  const degraded=await (await request("/api/first-car/queue")).json();
  assert.equal(degraded.pending,null);
  assert.equal(degraded.text_article,null);
  assert.deepEqual(degraded.queue,queue);
});
test("First Car dispatch is owner-only, fixed to main, and reuses active or recent runs",async(t)=>{
  const api="/api/first-car/collect";
  const {enabled,session,request}=firstCarSession();
  const workflow="/actions/workflows/first-car-dzen-collector.yml";
  const run={id:42,event:"workflow_dispatch",status:"in_progress",head_branch:"main",
    path:".github/workflows/first-car-dzen-collector.yml",created_at:new Date().toISOString()};
  let dispatched=false;
  const github=t.mock.method(globalThis,"fetch",async(input,options)=>{
    // workerd rejects redirect:"error" while constructing the outgoing request.
    if (options.redirect==="error") throw new TypeError("Unsupported redirect mode");
    assert.equal(options.redirect,"manual");
    assert.equal(new URL(input).origin,"https://api.github.com");
    assert.equal(options.headers.accept,"application/vnd.github+json");
    assert.equal(options.headers["x-github-api-version"],"2022-11-28");
    assert.equal(options.headers.cookie,undefined);
    const path=String(input).split("/iipike-site")[1];
    if(path==="/contents/dzen/queue.json?ref=first-car-data"){
      assert.equal(options.headers.authorization,"Bearer "+env.GITHUB_REPO_TOKEN);
      const queue={last_run:{id:42,processed:4,errors:1,added:2}};
      return Response.json({type:"file",sha:"queue-sha",content:Buffer.from(JSON.stringify(queue)).toString("base64")});
    }
    assert.equal(options.headers.authorization,"Bearer "+enabled.FIRST_CAR_ACTIONS_TOKEN);
    if(path===workflow+"/runs?branch=main&per_page=10")
      return Response.json({workflow_runs:dispatched?[run]:[]});
    if(path===workflow+"/dispatches"){
      assert.equal(dispatched,false);
      assert.deepEqual(JSON.parse(options.body),{ref:"main",return_run_details:true});
      dispatched=true;
      return Response.json({workflow_run_id:42});
    }
    if(path==="/actions/runs/42")return Response.json(run);
    throw Error("Unexpected request");
  });
  assert.equal((await request(api,{method:"POST",headers:{Origin:env.ADMIN_ORIGIN}})).status,401);
  assert.equal((await request(api,{method:"POST",headers:{...session,Origin:"https://wrong.test"}})).status,403);
  assert.equal((await call(api,{method:"POST",headers:session})).status,503);
  for(const [path,body] of [[api+"?ref=other",""],[api,"{}"],[api," "],[api,new Uint8Array([0])]]){
    const response=await request(path,{method:"POST",body});
    assert.equal(response.status,400);
    assert.deepEqual(await response.json(),{ok:false,error:"unexpected_input"});
  }
  assert.equal(github.mock.callCount(),0);
  const start=await request(api,{method:"POST",body:""});
  assert.equal(start.status,202);
  assert.equal((await start.json()).id,42);
  assert.equal((await (await request(api,{method:"POST",body:new Uint8Array(0)})).json()).state,"running");
  assert.equal((await (await request(api,{method:"POST"})).json()).state,"running");
  assert.equal((await (await request(api+"?run=42")).json()).state,"running");
  Object.assign(run,{status:"completed",conclusion:"success"});
  const complete=await (await request(api+"?run=42")).json();
  assert.deepEqual(complete,{ok:true,id:42,state:"completed",conclusion:"success",report:{processed:4,errors:1,added:2}});
  assert.equal((await (await request(api,{method:"POST"})).json()).state,"cooldown");
  run.path=".github/workflows/commenting-queue.yml";
  assert.equal((await request(api+"?run=42")).status,404);
});
test("First Car rejects upstream redirects and reports only safe failure diagnostics",async(t)=>{
  const {request}=firstCarSession();
  const marker="never-copy-token-or-cookie";
  const warn=t.mock.method(console,"warn",()=>{});
  let reply;
  const fetcher=t.mock.method(globalThis,"fetch",async(input,options)=>{
    assert.equal(options.redirect,"manual");
    assert.equal(new URL(input).origin,"https://api.github.com");
    if (String(input).endsWith("/dispatches")) throw new TypeError("Authorization: Bearer "+marker);
    return reply();
  });
  const cases=[
    {reply:()=>Response.json({message:marker},{status:302,headers:{Location:"https://other.example/"+marker}}),
      expected:{error:"first_car_runs_unavailable",stage:"list_runs",kind:"upstream_3xx",upstream_status:302},requests:1},
    {reply:()=>Response.json({message:marker},{status:403}),
      expected:{error:"first_car_runs_unavailable",stage:"list_runs",kind:"upstream_http",upstream_status:403},requests:1},
    {reply:()=>Response.json(null),
      expected:{error:"first_car_runs_unavailable",stage:"list_runs",kind:"invalid_response",upstream_status:200},requests:1},
    {reply:()=>Response.json({workflow_runs:[]}),
      expected:{error:"first_car_service_unavailable",stage:"dispatch",kind:"TypeError"},requests:2},
  ];
  for (const scenario of cases) {
    reply=scenario.reply;
    fetcher.mock.resetCalls();
    warn.mock.resetCalls();
    const response=await request("/api/first-car/collect",{method:"POST"});
    assert.equal(response.status,502);
    assert.deepEqual(await response.json(),{ok:false,...scenario.expected});
    assert.equal(fetcher.mock.callCount(),scenario.requests);
    const {error,...diagnostic}=scenario.expected;
    assert.deepEqual(warn.mock.calls[0].arguments,["first_car_failure",diagnostic]);
    assert.equal(warn.mock.callCount(),1);
  }
});
test("GitHub OAuth popup yields owner-only session; review is idempotent",async()=>{
  const previousFetch=globalThis.fetch;
  const written=new Map();
  globalThis.fetch=async (url,opts={})=>{
    const u=String(url);
    if(u==="https://github.com/login/oauth/access_token")
      return Response.json({access_token:"github-user-token"});
    if(u==="https://api.github.com/user")
      return Response.json({login:"AfterDark1000",id:284211090});
    const root="https://api.github.com/repos/AfterDark1000/iipike-site/contents/";
    assert.ok(u.startsWith(root));
    const path=decodeURIComponent(u.slice(root.length).split("?")[0]);
    if(path.startsWith("editorial_inbox/auto_drafts/"))
      return Response.json({type:"file",sha:"original-draft-sha",
        content:Buffer.from(JSON.stringify({article_id:"test-carbon-story",
          revision:4,updated_at:"2026-11-17T09:14:28.326Z",status:"ready_for_review"})).toString("base64")});
    if(path.startsWith("editorial_inbox/auto_decisions/")){
      if((opts.method||"GET")==="PUT"){
        assert.equal(written.has(path),false);
        written.set(path,JSON.parse(opts.body));
        return Response.json({commit:{sha:"test-write-commit"}}, {status:201});
      }
      return written.has(path) ? Response.json({type:"file",sha:"decision-sha"}) : Response.json({message:"Not Found"},{status:404});
    }
    throw Error("Unexpected Github endpoint "+u);
  };
  try {
    const start=await call("/auth/start");
    assert.equal(start.status,302);
    assert.match(start.headers.get("location"), /code_challenge=/);
    const cookie=start.headers.get("set-cookie").split(";")[0];
    const state=new URL(start.headers.get("location")).searchParams.get("state");
    const cb=await call("/auth/callback?code=sample-code&state="+encodeURIComponent(state),{headers:{Cookie:cookie}});
    assert.equal(cb.status,200);
    const html=await cb.text();
    const token=html.match(/"token":"([^"]+)"/)?.[1];
    assert.ok(token);
    // The Worker signs a fixed seven-day owner session.
    const payload=JSON.parse(Buffer.from(token.split(".")[0],"base64url").toString("utf8"));
    const ttl=payload.exp-Math.floor(Date.now()/1000);
    assert.ok(ttl>=7*24*3600-5 && ttl<=7*24*3600, "Owner session must expire in seven days");
    assert.match(html,/https:\/\/iipike\.ru/);
    const headers={Origin:env.ADMIN_ORIGIN,Authorization:"Bearer "+token};
    const session=await call("/api/session",{headers});
    assert.equal(session.status,200);
    assert.equal((await session.json()).login,"AfterDark1000");
    const review=await call("/api/review",{method:"POST",headers:{...headers,"content-type":"application/json"},
      body:JSON.stringify(exampleReview())});
    assert.equal(review.status,200);
    const decision=await review.json();
    assert.equal(decision.status,"feedback_pending_revision");
    assert.equal(written.size,1);
    assert.equal([...written.keys()][0],"editorial_inbox/auto_decisions/test-carbon-story-r4.json");
    const duplicate=await call("/api/review",{method:"POST",headers:{...headers,"content-type":"application/json"},body:JSON.stringify(exampleReview())});
    assert.equal(duplicate.status,409);
  } finally {
    globalThis.fetch=previousFetch;
  }
});

test("expired signed owner session cannot access protected APIs",async()=>{
  const raw=Buffer.from(JSON.stringify({kind:"session",user_id:284211090,
    login:"AfterDark1000",exp:Math.floor(Date.now()/1000)-1})).toString("base64url");
  const mac=createHmac("sha256",env.SESSION_SIGNING_KEY).update(raw).digest("base64url");
  const expired=await call("/api/session",{headers:{Origin:env.ADMIN_ORIGIN,
    Authorization:"Bearer "+raw+"."+mac}});
  assert.equal(expired.status,401);
  const invalid=await call("/api/session",{headers:{Origin:env.ADMIN_ORIGIN,
    Authorization:"Bearer "+raw+"."+mac.slice(0,-1)+"?"}});
  assert.equal(invalid.status,401);
});

test("misconfigured gateway returns only missing binding names",async()=>{
  const broken={...env};
  delete broken.GITHUB_CLIENT_SECRET;
  broken.SESSION_SIGNING_KEY="short";
  const r=await gateway.fetch(new Request(env.BACKEND_ORIGIN+"/health"),broken);
  assert.equal(r.status,503);
  const body=await r.json();
  assert.equal(body.error,"gateway_not_configured");
  assert.deepEqual(body.missing,["GITHUB_CLIENT_SECRET"]);
  assert.deepEqual(body.invalid,["SESSION_SIGNING_KEY_too_short"]);
  assert.equal(JSON.stringify(body).includes("short"),true); // validation flag only
  assert.equal(JSON.stringify(body).includes(env.SESSION_SIGNING_KEY),false);
  assert.equal(JSON.stringify(body).includes(env.GITHUB_REPO_TOKEN),false);
});


function fixtureWebP(){
  // Header-only mock for API tests; production CI decodes real WebP with Pillow.
  const raw=new Uint8Array(1500);
  const view=new DataView(raw.buffer);
  function put(off,str){for(let i=0;i<str.length;i++)raw[off+i]=str.charCodeAt(i)}
  put(0,"RIFF");view.setUint32(4,raw.length-8,true);put(8,"WEBP");put(12,"VP8X");
  view.setUint32(16,raw.length-20,true);
  const w=1600-1,h=900-1;
  raw[24]=w&255;raw[25]=(w>>8)&255;raw[26]=(w>>16)&255;
  raw[27]=h&255;raw[28]=(h>>8)&255;raw[29]=(h>>16)&255;
  return raw;
}
test("WebP header check rejects non-WebP and bad ratios",()=>{
  assert.deepEqual(__test.webpDimensions(fixtureWebP()),{width:1600,height:900});
  const png=fixtureWebP();png[0]=0;assert.throws(()=>__test.webpDimensions(png));
  const over=new Uint8Array(800_001);assert.throws(()=>__test.webpDimensions(over));
});
test("authenticated WebP upload is restricted to approved rev and never publishes",async()=>{
  const previous=globalThis.fetch, written=new Map();
  const approved={article_id:"test-cover-story",revision:4,updated_at:"2026-11-17T09:14:28.326Z",
    status:"text_approved_cover_pending",action:"approve_text",draft_blob_sha:"draft-sha"};
  const draft={article_id:approved.article_id,revision:4,updated_at:approved.updated_at,status:"ready_for_review"};
  const box=(obj,sha)=>Response.json({type:"file",sha,content:Buffer.from(JSON.stringify(obj)).toString("base64")});
  globalThis.fetch=async (url,opts={})=>{
    const urlstr=String(url);
    if(urlstr==="https://github.com/login/oauth/access_token")return Response.json({access_token:"user-oauth"});
    if(urlstr==="https://api.github.com/user")return Response.json({id:284211090,login:"AfterDark1000"});
    const base="https://api.github.com/repos/AfterDark1000/iipike-site/contents/";
    assert.ok(urlstr.startsWith(base));
    const path=urlstr.slice(base.length).split("?")[0];
    if(path==="editorial_inbox/auto_drafts/test-cover-story.json")return box(draft,"draft-sha");
    if(path==="editorial_inbox/auto_decisions/test-cover-story-r4.json")return box(approved,"decision-sha");
    if(path.startsWith("editorial_inbox/auto_covers/")){
      if((opts.method||"GET")==="PUT"){
        if(written.has(path))return Response.json({message:"Exists"},{status:409});
        const value=JSON.parse(opts.body);
        const bytes=Buffer.from(value.content,"base64");
        const sha=createHash("sha1").update(Buffer.concat([Buffer.from("blob "+bytes.length+"\0"),bytes])).digest("hex");
        written.set(path,{content:value.content,sha});
        return Response.json({content:{sha},commit:{sha:"new-commit"}},{status:201});
      }
      const saved=written.get(path);
      return saved?Response.json({type:"file",sha:saved.sha,content:saved.content}):
        Response.json({message:"Not Found"},{status:404});
    }
    throw Error("Unexpected path "+path);
  };
  try{
    const begin=await call("/auth/start");
    const cookie=begin.headers.get("set-cookie").split(";")[0];
    const state=new URL(begin.headers.get("location")).searchParams.get("state");
    const cb=await call("/auth/callback?code=ok&state="+state,{headers:{Cookie:cookie}});
    const html=await cb.text();
    const token=html.match(/"token":"([^"]+)"/)?.[1];
    assert.ok(token);
    const form=new FormData();
    form.set("article_id",draft.article_id);form.set("revision","4");
    form.set("updated_at",draft.updated_at);form.set("headline","РОЙ АГЕНТОВ");
    form.set("concept","Редакционная графика с распределением задач");
    form.set("file",new File([fixtureWebP()],"cover.webp",{type:"image/webp"}));
    const unauthorized=await call("/api/cover-upload",{method:"POST",body:form,headers:{Origin:env.ADMIN_ORIGIN}});
    assert.equal(unauthorized.status,401);
    const headers={Origin:env.ADMIN_ORIGIN,Authorization:"Bearer "+token};
    const result=await call("/api/cover-upload",{method:"POST",body:form,headers});
    assert.equal(result.status,200,await result.clone().text());
    const response=await result.json();
    assert.equal(response.status,"ready_for_cover_review");
    assert.equal(response.width,1600);assert.equal(response.height,900);
    assert.equal(written.size,2);
    assert.ok(written.has("editorial_inbox/auto_covers/test-cover-story-r4-v1.webp"));
    assert.ok(written.has("editorial_inbox/auto_covers/test-cover-story-r4-v1.json"));
    const duplicate=await call("/api/cover-upload",{method:"POST",body:form,headers});
    assert.equal(duplicate.status,409);
    assert.equal(written.size,2);
  }finally{globalThis.fetch=previous}
});

test("GitHub OAuth exchange refusal returns safe human-readable reason for mobile",async()=>{
  const original=globalThis.fetch;
  let issued=0;
  globalThis.fetch=async (url)=>{
    assert.equal(String(url),"https://github.com/login/oauth/access_token");
    issued+=1;
    if(issued===1)return Response.json({error:"bad_verification_code",
      error_description:"private GitHub diagnostic that must not be disclosed"});
    return Response.json({error:"<script>private token</script>"},{status:401});
  };
  try{
    for(const expected of ["bad_verification_code","unknown_exchange_error"]){
      const start=await call("/auth/start");
      assert.equal(start.status,302);
      const state=new URL(start.headers.get("location")).searchParams.get("state");
      const cookie=start.headers.get("set-cookie").split(";")[0];
      const callback=await call("/auth/callback?code=one-use-test-code&state="+encodeURIComponent(state),{
        headers:{Cookie:cookie}
      });
      assert.equal(callback.status,401);
      assert.match(callback.headers.get("content-type"),/text\/html/);
      const page=await callback.text();
      assert.ok(page.includes("Не удалось войти через GitHub"));
      assert.ok(page.includes(expected));
      assert.ok(page.includes("hpii-auth-error"));
      assert.ok(!page.includes("private GitHub diagnostic"));
      assert.ok(!page.includes("<script>private token</script>"));
      assert.ok(!page.includes(env.GITHUB_CLIENT_SECRET));
      assert.ok(!page.includes(env.GITHUB_REPO_TOKEN));
      assert.ok(!page.includes("one-use-test-code"));
      assert.equal(callback.headers.get("cache-control"),"no-store");
    }
  }finally{globalThis.fetch=original}
});

test("cover decisions require approved text, exact WebP hash, login and are write-once",async()=>{
  const sha="a".repeat(40), written=new Map(), prior=globalThis.fetch;
  const id="test-cover-approval",time="2026-11-17T09:14:28.326Z";
  const draft={article_id:id,revision:4,updated_at:time,status:"ready_for_review"};
  const textDecision={article_id:id,revision:4,updated_at:time,action:"approve_text",
    status:"text_approved_cover_pending",draft_blob_sha:"draft-sha"};
  const cover={schema_version:1,article_id:id,text_revision:4,text_updated_at:time,status:"ready_for_cover_review",
    source_draft_blob_sha:"draft-sha",source_decision_blob_sha:"text-sha",
    image_path:"editorial_inbox/auto_covers/"+id+"-r4-v1.webp",
    image_blob_sha:sha,width:1600,height:900};
  const box=(obj,blob)=>Response.json({type:"file",sha:blob,
    content:Buffer.from(JSON.stringify(obj)).toString("base64")});
  globalThis.fetch=async(url,options={})=>{
    const u=String(url);
    if(u==="https://github.com/login/oauth/access_token")return Response.json({access_token:"ok"});
    if(u==="https://api.github.com/user")return Response.json({id:284211090,login:"AfterDark1000"});
    const root="https://api.github.com/repos/AfterDark1000/iipike-site/contents/";
    assert.ok(u.startsWith(root));
    const path=u.slice(root.length).split("?")[0];
    if(path==="editorial_inbox/auto_drafts/"+id+".json")return box(draft,"draft-sha");
    if(path==="editorial_inbox/auto_decisions/"+id+"-r4.json")return box(textDecision,"text-sha");
    if(path==="editorial_inbox/auto_covers/"+id+"-r4-v1.json")return box(cover,"cover-meta-sha");
    if(path==="editorial_inbox/auto_covers/"+id+"-r4-v1.webp")return Response.json({type:"file",sha});
    if(path==="editorial_inbox/auto_cover_decisions/"+id+"-r4-v1.json"){
      if(options.method==="PUT"){
        assert.equal(written.size,0);
        const body=JSON.parse(options.body);
        assert.equal(body.branch,"editorial-intake");
        const content=JSON.parse(Buffer.from(body.content,"base64").toString("utf8"));
        written.set(path,content);
        return Response.json({content:{sha:"new-sha"},commit:{sha:"commit-cover"}},{status:201});
      }
      if(written.size)return box([...written.values()][0],"decision-sha");
      return Response.json({message:"Not Found"},{status:404});
    }
    throw Error("Unknown Github path "+path);
  };
  try{
    const start=await call("/auth/start");
    const cookie=start.headers.get("set-cookie").split(";")[0];
    const state=new URL(start.headers.get("location")).searchParams.get("state");
    const cb=await call("/auth/callback?code=ok&state="+state,{headers:{Cookie:cookie}});
    const html=await cb.text();
    const token=html.match(/"token":"([^"]+)"/)?.[1];
    assert.ok(token);
    const payload={article_id:id,revision:4,text_updated_at:time,cover_version:1,
      image_blob_sha:sha,action:"approve_cover",note:"Проверено"};
    const headers={Origin:env.ADMIN_ORIGIN,"Content-Type":"application/json"};
    let response=await call("/api/cover-review",{method:"POST",headers,body:JSON.stringify(payload)});
    assert.equal(response.status,401);
    assert.equal(written.size,0);
    headers.Authorization="Bearer "+token;
    response=await call("/api/cover-review",{method:"POST",headers,body:JSON.stringify({...payload,image_blob_sha:"b".repeat(40)})});
    assert.equal(response.status,409);
    assert.equal(written.size,0);
    response=await call("/api/cover-review",{method:"POST",headers,body:JSON.stringify(payload)});
    assert.equal(response.status,200,await response.clone().text());
    assert.equal((await response.json()).status,"cover_approved_handoff_pending");
    const saved=[...written.values()][0];
    assert.equal(saved.cover_blob_sha,sha);
    assert.equal(saved.cover_metadata_blob_sha,"cover-meta-sha");
    assert.equal(saved.action,"approve_cover");
    assert.equal(saved.status,"cover_approved_handoff_pending");
    response=await call("/api/cover-review",{method:"POST",headers,body:JSON.stringify(payload)});
    assert.equal(response.status,409);
    assert.equal(written.size,1);
  }finally{globalThis.fetch=prior}
});
test("cover-review validation fails closed for unexpected actions and blank rework notes",()=>{
  const base={article_id:"test-cover",revision:4,text_updated_at:"2026-11-17T09:14:28.326Z",
    cover_version:1,image_blob_sha:"a".repeat(40),action:"revise_cover",note:"Переделать фон"};
  assert.equal(__test.validCoverReview(base),true);
  assert.equal(__test.validCoverReview({...base,note:""}),false);
  assert.equal(__test.validCoverReview({...base,action:"publish"}),false);
  assert.equal(__test.validCoverReview({...base,image_blob_sha:"bad"}),false);
  assert.equal(__test.validCoverReview({...base,cover_version:2}),true);
  assert.equal(__test.validCoverReview({...base,cover_version:0}),false);
  assert.equal(__test.validCoverReview({...base,cover_version:6}),false);
  assert.equal(__test.validCoverReview({...base,admin:true}),false);
});

test("editorial admin lists use the server GitHub token and reject anonymous or broad requests",async(t)=>{
  const {request}=firstCarSession();
  const sha="a".repeat(40);
  const calls=[];
  const github=t.mock.method(globalThis,"fetch",async(input,options={})=>{
    const url=String(input),path=url.split("/iipike-site")[1];
    calls.push(path);
    assert.equal(options.headers.authorization,"Bearer "+env.GITHUB_REPO_TOKEN);
    assert.equal(options.headers.accept,"application/vnd.github+json");
    if(path==="/contents/editorial_inbox/auto_drafts?ref=editorial-intake")
      return Response.json([
        {name:"draft-one.json",type:"file",sha},
        {name:"ignore.txt",type:"file",sha},
        {name:"nested",type:"dir",sha}
      ]);
    if(path==="/contents/editorial_inbox/auto_copyedits?ref=editorial-intake")
      return Response.json([
        {name:"copy-one-r2-v1.json",type:"file",sha},
        {name:"bad-r0-v1.json",type:"file",sha}
      ]);
    throw Error("Unexpected GitHub request "+path);
  });
  const anonymous=await call("/api/editorial-files?kind=drafts",{headers:{Origin:env.ADMIN_ORIGIN}});
  assert.equal(anonymous.status,401);
  assert.equal(github.mock.callCount(),0);
  assert.equal((await request("/api/editorial-files?kind=drafts&ref=main")).status,400);
  assert.equal((await request("/api/editorial-files?kind=unknown")).status,400);
  assert.equal(github.mock.callCount(),0);
  const drafts=await (await request("/api/editorial-files?kind=drafts")).json();
  assert.deepEqual(drafts.entries,[{
    name:"draft-one.json",type:"file",sha,
    download_url:"https://raw.githubusercontent.com/AfterDark1000/iipike-site/editorial-intake/editorial_inbox/auto_drafts/draft-one.json"
  }]);
  const copies=await (await request("/api/editorial-files?kind=copyedits")).json();
  assert.deepEqual(copies.entries,[{
    name:"copy-one-r2-v1.json",type:"file",sha,
    download_url:"https://raw.githubusercontent.com/AfterDark1000/iipike-site/editorial-intake/editorial_inbox/auto_copyedits/copy-one-r2-v1.json"
  }]);
  assert.deepEqual(calls,[
    "/contents/editorial_inbox/auto_drafts?ref=editorial-intake",
    "/contents/editorial_inbox/auto_copyedits?ref=editorial-intake"
  ]);
});
test("editorial record fallback is path-limited, owner-only and distinguishes missing files from GitHub failures",async(t)=>{
  const {request}=firstCarSession();
  const record={article_id:"test-story",revision:2,status:"ready_for_review"};
  const path="editorial_inbox/auto_decisions/test-story-r2.json";
  let status=200;
  const github=t.mock.method(globalThis,"fetch",async(input,options={})=>{
    assert.equal(String(input),"https://api.github.com/repos/AfterDark1000/iipike-site/contents/"+path+"?ref=editorial-intake");
    assert.equal(options.headers.authorization,"Bearer "+env.GITHUB_REPO_TOKEN);
    if(status===404)return Response.json({message:"Not Found"},{status});
    if(status!==200)return Response.json({message:"GitHub failure"},{status});
    return Response.json({type:"file",sha:"b".repeat(40),
      content:Buffer.from(JSON.stringify(record)).toString("base64")});
  });
  const bad=await request("/api/editorial-record?path="+encodeURIComponent("../secrets"));
  assert.equal(bad.status,400);
  assert.equal(github.mock.callCount(),0);
  const found=await (await request("/api/editorial-record?path="+encodeURIComponent(path))).json();
  assert.deepEqual(found,{ok:true,found:true,record});
  status=404;
  const missing=await (await request("/api/editorial-record?path="+encodeURIComponent(path))).json();
  assert.deepEqual(missing,{ok:true,found:false});
  status=403;
  assert.equal((await request("/api/editorial-record?path="+encodeURIComponent(path))).status,502);
  assert.equal(github.mock.callCount(),3);
});
