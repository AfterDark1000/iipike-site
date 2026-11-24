import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import gateway,{__test} from "../src/index.mjs";
globalThis.crypto ||= webcrypto;
const env={ADMIN_ORIGIN:"https://iipike.ru",BACKEND_ORIGIN:"https://hpii-auth.example.workers.dev",GITHUB_CLIENT_ID:"fake-client",GITHUB_CLIENT_SECRET:"fake-secret",SESSION_SIGNING_KEY:"testing-only-secret-which-is-much-longer-than-32",GITHUB_REPO_TOKEN:"fake-token",ALLOWED_GITHUB_USER_ID:"284211090"};
const root="https://api.github.com/repos/AfterDark1000/iipike-site";
const article_id="example-copyedit",revision=2,version=1,source_sha="a".repeat(40),candidate_sha="b".repeat(40),base="c".repeat(40),tree="d".repeat(40),newtree="e".repeat(40),commit="f".repeat(40);
const stem=article_id+"-r2-v1",draftPath="editorial_inbox/auto_drafts/"+article_id+".json",candidatePath="editorial_inbox/auto_copyedits/"+stem+".json",decisionPath="editorial_inbox/auto_copyedit_decisions/"+stem+".json";
const original={title:"Заголовок",dzen_title:"Заголовок",summary:"Факт",article_markdown:"Новая модель решает 12 задач.\n\nСсылка https://example.com/news",threads_text:"Факт",x_text:"Факт @example",vk_title:"🌍 Заголовок",vk_summary:"Факт"};
const edited={...original,title:"Новый заголовок",dzen_title:"Новый заголовок",article_markdown:"Модель решает 12 задач.\n\nПодробности https://example.com/news"};
const draft={article_id,revision,status:"ready_for_review",updated_at:"2026-11-24T08:03:46Z",content:{...original,topics:["science"],related_dzen_ids:[]},editor_notes:["original"],cover_brief:{fact:"original"}};
const candidate={schema_version:2,worker:"hpii-chief-copyeditor",article_id,source_revision:revision,copyedit_version:version,source_draft_blob_sha:source_sha,source_updated_at:draft.updated_at,status:"ready_for_comparison",original_text:original,edited_text:edited,editor_flags:[]};
const data={article_id,revision,version,source_sha,candidate_sha,action:"accept_copyedit",note:""};
const box=(obj,sha)=>Response.json({type:"file",sha,content:Buffer.from(JSON.stringify(obj)).toString("base64")});
const missing=()=>Response.json({}, {status:404});
const call=(p,o={})=>gateway.fetch(new Request(env.BACKEND_ORIGIN+p,o),env);
async function login(){
 const start=await call("/auth/start");const cookie=start.headers.get("set-cookie").split(";")[0];
 const state=new URL(start.headers.get("location")).searchParams.get("state");
 const cb=await call("/auth/callback?code=ok&state="+state,{headers:{Cookie:cookie}});
 const token=(await cb.text()).match(/"token":"([^"]+)"/)?.[1];assert.ok(token);
 return {Origin:env.ADMIN_ORIGIN,Authorization:"Bearer "+token,"content-type":"application/json"};
}
test("copyedit package protects source, facts, original and social limits",()=>{
 assert.equal(__test.validCopyReview(data),true);
 assert.equal(__test.validCopyReview({...data,action:"revise_copyedit",note:""}),false);
 assert.equal(__test.validCopyReview({...data,article_id:"../bad"}),false);
 assert.equal(__test.validCopyPackage(draft,candidate,data),true);
 for(const change of [{article_markdown:edited.article_markdown.replace("12","13")},{article_markdown:edited.article_markdown.replace("https://example.com/news","https://bad.com")},{x_text:"Факт @other"},{threads_text:"а".repeat(481)}]){
  assert.equal(__test.validCopyPackage(draft,{...candidate,edited_text:{...edited,...change}},data),false);
 }
 assert.equal(__test.validCopyPackage(draft,{...candidate,original_text:{...original,summary:"not exact"}},data),false);
 assert.equal(__test.validCopyPackage(draft,{...candidate,status:"needs_editor_attention"},data),false);
});
test("authenticated accept is one non-forced Git ref update; keep/return do not change draft",async()=>{
 const saved=globalThis.fetch;let writes=[],human=false,decision=false,newer=false,stale=false,race=false;
 globalThis.fetch=async(url,opts={})=>{
  const u=String(url);
  if(u==="https://github.com/login/oauth/access_token")return Response.json({access_token:"user-token"});
  if(u==="https://api.github.com/user")return Response.json({id:284211090,login:"AfterDark1000"});
  assert.ok(u.startsWith(root),u);
  const p=u.slice(root.length);
  if(p==="/git/ref/heads/editorial-intake")return Response.json({object:{sha:base}});
  if(p==="/git/commits/"+base)return Response.json({tree:{sha:tree}});
  if(p.startsWith("/contents/")){
   assert.ok(p.endsWith("?ref="+base),p);
   const loc=p.slice("/contents/".length).split("?")[0];
   if(loc===draftPath)return box(draft,stale?"9".repeat(40):source_sha);
   if(loc===candidatePath)return box(candidate,candidate_sha);
   if(loc===decisionPath)return decision?box({}, "1".repeat(40)):missing();
   if(loc==="editorial_inbox/auto_decisions/"+article_id+"-r2.json")return human?box({}, "2".repeat(40)):missing();
   if(loc==="editorial_inbox/auto_copyedits")return Response.json([{name:stem+".json"},...(newer?[{name:article_id+"-r2-v2.json"}]:[])]);
   throw Error(p);
  }
  const body=JSON.parse(opts.body);writes.push({p,body});
  if(p==="/git/trees")return Response.json({sha:newtree},{status:201});
  if(p==="/git/commits")return Response.json({sha:commit},{status:201});
  if(p==="/git/refs/heads/editorial-intake")return race?Response.json({}, {status:422}):Response.json({object:{sha:commit}});
  throw Error(p);
 };
 try{
  const headers=await login(),submit=d=>call("/api/copyedit-review",{method:"POST",headers,body:JSON.stringify(d)});
  const denied=await call("/api/copyedit-review",{method:"POST",headers:{Origin:env.ADMIN_ORIGIN,"content-type":"application/json"},body:JSON.stringify(data)});
  assert.equal(denied.status,401);
  for(const flag of ["human","decision","newer","stale"]){
   human=flag==="human";decision=flag==="decision";newer=flag==="newer";stale=flag==="stale";
   assert.equal((await submit(data)).status,409);assert.equal(writes.length,0);
  }
  human=decision=newer=stale=false;
  let r=await submit(data);assert.equal(r.status,200,await r.clone().text());
  assert.equal((await r.json()).status,"copyedit_applied");
  assert.equal(writes.length,3);
  const entries=writes[0].body.tree;assert.equal(entries.length,2);
  const next=JSON.parse(entries.find(x=>x.path===draftPath).content),record=JSON.parse(entries.find(x=>x.path===decisionPath).content);
  assert.equal(next.revision,3);assert.equal(next.status,"ready_for_review");assert.equal(next.content.title,edited.title);assert.deepEqual(next.cover_brief,draft.cover_brief);assert.deepEqual(next.content.topics,draft.content.topics);assert.equal(record.action,"accept_copyedit");
  assert.ok(next.editor_notes.at(-1).includes(candidate_sha));assert.equal(writes[2].body.force,false);assert.deepEqual(writes[1].body.parents,[base]);
  for(const action of ["keep_original","revise_copyedit"]){writes=[];r=await submit({...data,action,note:"Уточни начало"});assert.equal(r.status,200,await r.clone().text());assert.equal(writes[0].body.tree.length,1);assert.equal(writes[0].body.tree[0].path,decisionPath)}
  writes=[];race=true;r=await submit(data);assert.equal(r.status,409);assert.equal(writes[2].body.force,false);
 }finally{globalThis.fetch=saved}
});
