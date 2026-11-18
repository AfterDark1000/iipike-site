import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto,createHash} from "node:crypto";
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
