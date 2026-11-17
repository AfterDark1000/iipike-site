import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
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
