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

test("owner article edits submit only a version-bound request, never rewrite the live source",async()=>{
 const saved=globalThis.fetch,writes=[];let pending=null;
 const doc={slug:"one",status:"approved",title:"Статья",cover:"assets/editorial/one.webp",article_markdown:"Текст"};
 globalThis.fetch=async(url,opts={})=>{
   const u=String(url);
   if(u==="https://github.com/login/oauth/access_token")return Response.json({access_token:"user-token"});
   if(u==="https://api.github.com/user")return Response.json({id:284211090,login:"AfterDark1000"});
   assert.ok(u.startsWith(root),u);const p=u.slice(root.length);
   if(p==="/git/ref/heads/main")return Response.json({object:{sha:head}});
   if(p==="/contents/news.json?ref="+head)return box(rows,"d".repeat(40));
   if(p==="/contents/content/approved/one.json?ref="+head)return box(doc,sha);
   if(p==="/contents/data/article_edits/requests/one.json?ref="+head)return pending?box(pending,next):Response.json({}, {status:404});
   if(p==="/contents/data/article_edits/receipts/one.json?ref="+head)return Response.json({}, {status:404});
   if(p==="/contents/data/article_edits/requests/one.json"&&opts.method==="PUT"){
     const b=JSON.parse(opts.body);writes.push(b);pending=JSON.parse(Buffer.from(b.content,"base64"));
     return Response.json({commit:{sha:next},content:{sha:next}},{status:201});
   }
   throw Error(p);
 };
 try{
  assert.equal((await call("/api/article-edit?article_id=one",{headers:{Origin:env.ADMIN_ORIGIN}})).status,401);
  const headers=await login();
  const get=await call("/api/article-edit?article_id=one",{headers});assert.equal(get.status,200);assert.equal((await get.json()).markdown,"Текст");
  const send=d=>call("/api/article-edit",{method:"POST",headers,body:JSON.stringify(d)});
  const d={article_id:"one",base_sha:sha,article_markdown:"Исправленный текст"};
  assert.equal((await send({...d,base_sha:next})).status,409);
  assert.equal((await send({...d,title:"Подмена"})).status,400);
  const res=await send(d);assert.equal(res.status,202);assert.equal((await res.json()).status,"queued");
  assert.equal(writes.length,1);assert.equal(pending.article_markdown,d.article_markdown);
  assert.equal((await send(d)).status,409);assert.equal(writes.length,1);
 }finally{globalThis.fetch=saved}
});
