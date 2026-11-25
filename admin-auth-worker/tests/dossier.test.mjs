import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import gateway,{__test} from "../src/index.mjs";
globalThis.crypto ||= webcrypto;
const env={ADMIN_ORIGIN:"https://iipike.ru",BACKEND_ORIGIN:"https://hpii-auth.example.workers.dev",GITHUB_CLIENT_ID:"fake-client",GITHUB_CLIENT_SECRET:"fake-secret",SESSION_SIGNING_KEY:"testing-only-secret-which-is-much-longer-than-32",GITHUB_REPO_TOKEN:"fake-token",ALLOWED_GITHUB_USER_ID:"284211090"};
const root="https://api.github.com/repos/AfterDark1000/iipike-site",head="a".repeat(40),sha="b".repeat(40),next="c".repeat(40);
const cfg={schema_version:1,items:["one"]};
const rows=["one","two"].map(id=>({id,title:id,url:"articles/"+id+"/",cover:"assets/editorial/"+id+".webp",published:"2026-11-25",rubric:"news"}));
const box=(obj,hash)=>Response.json({type:"file",sha:hash,content:Buffer.from(JSON.stringify(obj)).toString("base64")});
const call=(p,o={})=>gateway.fetch(new Request(env.BACKEND_ORIGIN+p,o),env);
async function login(){
 const start=await call("/auth/start");const cookie=start.headers.get("set-cookie").split(";")[0];
 const state=new URL(start.headers.get("location")).searchParams.get("state");
 const cb=await call("/auth/callback?code=ok&state="+state,{headers:{Cookie:cookie}});
 const token=(await cb.text()).match(/"token":"([^"]+)"/)?.[1];assert.ok(token);
 return {Origin:env.ADMIN_ORIGIN,Authorization:"Bearer "+token,"content-type":"application/json"};
}
test("Dossier membership validation rejects path, duplicate and arbitrary data",()=>{
 assert.equal(__test.validDossierConfig(cfg),true);
 for(const items of [["one","one"],["../one"],[null]])assert.equal(__test.validDossierConfig({schema_version:1,items}),false);
 const action={action:"add",article_id:"two",config_sha:sha};
 assert.equal(__test.validDossierAction(action),true);
 assert.equal(__test.validDossierAction({...action,path:"news.json"}),false);
 assert.equal(__test.validDossierAction({...action,action:"publish"}),false);
});
test("owner-only changes exactly one membership file; stale and draft requests do not write",async()=>{
 const saved=globalThis.fetch;const writes=[];let race=false;
 globalThis.fetch=async(url,opts={})=>{
  const u=String(url);
  if(u==="https://github.com/login/oauth/access_token")return Response.json({access_token:"user-token"});
  if(u==="https://api.github.com/user")return Response.json({id:284211090,login:"AfterDark1000"});
  assert.ok(u.startsWith(root),u);const p=u.slice(root.length);
  if(p==="/git/ref/heads/main")return Response.json({object:{sha:head}});
  if(p==="/contents/data/dossier.json?ref="+head)return box(cfg,sha);
  if(p==="/contents/news.json?ref="+head)return box(rows,"d".repeat(40));
  if(p==="/contents/data/dossier.json"&&opts.method==="PUT"){
   const b=JSON.parse(opts.body);writes.push(b);
   return race?Response.json({}, {status:409}):Response.json({commit:{sha:next},content:{sha:next}});
  }
  throw Error(p);
 };
 try{
  assert.equal((await call("/api/dossier",{headers:{Origin:env.ADMIN_ORIGIN}})).status,401);
  const headers=await login();
  const get=await call("/api/dossier",{headers});assert.equal(get.status,200);assert.deepEqual((await get.json()).config,cfg);
  const send=d=>call("/api/dossier",{method:"POST",headers,body:JSON.stringify(d)});
  const d={article_id:"two",action:"add",config_sha:sha};
  assert.equal((await send({...d,config_sha:next})).status,409);
  assert.equal((await send({...d,article_id:"draft"})).status,400);
  assert.equal(writes.length,0);
  const result=await send(d);assert.equal(result.status,200);
  assert.equal((await result.json()).status,"saved_pending_site_refresh");
  assert.equal(writes.length,1);assert.equal(writes[0].branch,"main");assert.equal(writes[0].sha,sha);
  assert.deepEqual(JSON.parse(Buffer.from(writes[0].content,"base64")), {schema_version:1,items:["two","one"]});
  const remove=await send({...d,article_id:"one",action:"remove"});assert.equal(remove.status,200);
  assert.deepEqual(JSON.parse(Buffer.from(writes[1].content,"base64")), {schema_version:1,items:[]});
  race=true;assert.equal((await send(d)).status,409);
 }finally{globalThis.fetch=saved}
});
