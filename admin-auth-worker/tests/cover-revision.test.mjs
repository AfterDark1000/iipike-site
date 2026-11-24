import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import gateway from "../src/index.mjs";
globalThis.crypto ||= webcrypto;
const env={
 ADMIN_ORIGIN:"https://iipike.ru",
 BACKEND_ORIGIN:"https://hpii-auth.example.workers.dev",
 GITHUB_CLIENT_ID:"fake-client",GITHUB_CLIENT_SECRET:"fake-secret",
 SESSION_SIGNING_KEY:"testing-only-secret-which-is-much-longer-than-32",
 GITHUB_REPO_TOKEN:"fake-token",ALLOWED_GITHUB_USER_ID:"284211090"
};
const base="https://api.github.com/repos/AfterDark1000/iipike-site/contents/";
function box(obj,sha){return Response.json({type:"file",sha,content:Buffer.from(JSON.stringify(obj)).toString("base64")})}
function call(path,opts={}){return gateway.fetch(new Request(env.BACKEND_ORIGIN+path,opts),env)}
async function login(){
 const start=await call("/auth/start");
 const cookie=start.headers.get("set-cookie").split(";")[0];
 const state=new URL(start.headers.get("location")).searchParams.get("state");
 const cb=await call("/auth/callback?code=ok&state="+state,{headers:{Cookie:cookie}});
 const token=(await cb.text()).match(/"token":"([^"]+)"/)?.[1];
 assert.ok(token);
 return {Origin:env.ADMIN_ORIGIN,Authorization:"Bearer "+token};
}

test("v2 cover review accepts only explicitly rejected v1, protects source and writes exact v2",async()=>{
 const original=globalThis.fetch,article_id="test-cover-review-v2",revision=3;
 const date="2026-11-18T02:50:00.000Z",sha="b".repeat(40);
 const draft={article_id,revision,updated_at:date,status:"ready_for_review"};
 const approve={article_id,revision,updated_at:date,action:"approve_text",status:"text_approved_cover_pending",draft_blob_sha:"draft-sha"};
 const cover={schema_version:1,article_id,text_revision:revision,text_updated_at:date,status:"ready_for_cover_review",source_draft_blob_sha:"draft-sha",source_decision_blob_sha:"text-sha",image_path:"editorial_inbox/auto_covers/"+article_id+"-r3-v2.webp",image_blob_sha:sha,width:1600,height:900};
 const parent={article_id,text_revision:3,text_updated_at:date,cover_version:1,action:"revise_cover",status:"cover_revision_requested",note:"Нужен одетый персонаж и другой стиль"};
 let parentStatus="missing",textState="approved",writes=[];
 globalThis.fetch=async(url,options={})=>{
   const u=String(url);
   if(u==="https://github.com/login/oauth/access_token")return Response.json({access_token:"user-token"});
   if(u==="https://api.github.com/user")return Response.json({id:284211090,login:"AfterDark1000"});
   assert.ok(u.startsWith(base),u);
   const p=u.slice(base.length).split("?")[0];
   if(p==="editorial_inbox/auto_drafts/"+article_id+".json")return box(draft,"draft-sha");
   if(p==="editorial_inbox/auto_decisions/"+article_id+"-r3.json")return textState==="missing"?Response.json({message:"Not Found"},{status:404}):box(textState==="rejected"?{...approve,action:"reject",status:"rejected"}:approve,"text-sha");
   if(p==="editorial_inbox/auto_covers/"+article_id+"-r3-v2.json")return box(cover,"cover-meta-sha");
   if(p==="editorial_inbox/auto_covers/"+article_id+"-r3-v2.webp")return Response.json({type:"file",sha});
   if(p==="editorial_inbox/auto_cover_decisions/"+article_id+"-r3-v1.json")
     return parentStatus==="missing"?Response.json({message:"Not Found"},{status:404}):
       box({...parent,status:parentStatus==="approved"?"cover_approved_handoff_pending":parent.status,action:parentStatus==="approved"?"approve_cover":parent.action},"parent-sha");
   if(p==="editorial_inbox/auto_cover_decisions/"+article_id+"-r3-v2.json"){
     if(options.method==="PUT"){
       const data=JSON.parse(Buffer.from(JSON.parse(options.body).content,"base64").toString("utf8"));
       writes.push(data);
       return Response.json({content:{sha:"saved"},commit:{sha:"commit"}},{status:201});
     }
     return writes.length?box(writes[0],"saved"):Response.json({message:"Not Found"},{status:404});
   }
   throw Error("Unexpected path "+p);
 };
 try{
  const auth=await login();
  const payload={article_id,revision,text_updated_at:date,cover_version:2,image_blob_sha:sha,action:"approve_cover",note:"Годится"};
  const headers={...auth,"content-type":"application/json"};
  let res=await call("/api/cover-review",{method:"POST",headers,body:JSON.stringify(payload)});
  assert.equal(res.status,409);assert.equal(writes.length,0);
  parentStatus="approved";
  res=await call("/api/cover-review",{method:"POST",headers,body:JSON.stringify(payload)});
  assert.equal(res.status,409);assert.equal(writes.length,0);
  parentStatus="rejected";
  res=await call("/api/cover-review",{method:"POST",headers,body:JSON.stringify({...payload,image_blob_sha:"a".repeat(40)})});
  assert.equal(res.status,409);assert.equal(writes.length,0);
  res=await call("/api/cover-review",{method:"POST",headers,body:JSON.stringify(payload)});
  assert.equal(res.status,200,await res.clone().text());
  assert.equal(writes.length,1);
  assert.equal(writes[0].cover_version,2);
  assert.equal(writes[0].status,"cover_approved_handoff_pending");
  writes.length=0;
  textState="missing";
  // Legacy candidate cannot be approved after its bound decision vanishes.
  res=await call("/api/cover-review",{method:"POST",headers,body:JSON.stringify(payload)});
  assert.equal(res.status,409);assert.equal(writes.length,0);
  cover.source_decision_blob_sha=null;
  res=await call("/api/cover-review",{method:"POST",headers,body:JSON.stringify(payload)});
  assert.equal(res.status,200,await res.clone().text());
  assert.equal(writes[0].source_text_decision_blob_sha,null);
  writes.length=0;textState="rejected";
  res=await call("/api/cover-review",{method:"POST",headers,body:JSON.stringify(payload)});
  assert.equal(res.status,409);assert.equal(writes.length,0);
  textState="approved";
  res=await call("/api/cover-review",{method:"POST",headers,body:JSON.stringify(payload)});
  assert.equal(res.status,200,await res.clone().text());
  assert.equal(writes[0].source_text_decision_blob_sha,"text-sha");
 }finally{globalThis.fetch=original}
});
