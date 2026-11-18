import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const html=fs.readFileSync(new URL("../admin/auto-editor/index.html",import.meta.url),"utf8");
const script=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)?.[1];
assert.ok(script,"Inline auto-editor script must exist");
const executable=script.replace(/\}\)\(\);\s*$/, "globalThis.__queueTests={classify};})();");
assert.notEqual(executable,script,"Expected explicit IIFE ending");

const slug="example-ai-story-1234567890abcdef", revision=3;
const updated="2026-11-18T10:00:00Z";
const doc={article_id:slug,revision,updated_at:updated,status:"ready_for_review",pool_sequence:45,content:{title:"Нормальный русский заголовок"}};
const key=slug+"-r3";
const raw="https://raw.githubusercontent.com/AfterDark1000/iipike-site/editorial-intake/editorial_inbox/";
const textDecision={article_id:slug,revision,updated_at:updated,status:"text_approved_cover_pending",action:"approve_text"};
const cover=v=>({article_id:slug,text_revision:3,text_updated_at:updated,status:"ready_for_cover_review",image_path:"editorial_inbox/auto_covers/"+key+"-v"+v+".webp",image_blob_sha:"b".repeat(40)});
const coverDecision=(v,action,status)=>({article_id:slug,text_revision:3,text_updated_at:updated,cover_version:v,cover_blob_sha:"b".repeat(40),action,status});
const handoff=v=>({article_id:slug,text_revision:3,cover_version:v,cover_blob_sha:"b".repeat(40),status:"handed_off_to_site_queue"});
function model(attachments={}){
 const responses=new Map(Object.entries(attachments).map(([p,value])=>[raw+p,value]));
 const noop=()=>{};
 const docStub={getElementById:()=>({addEventListener:noop}),querySelectorAll:()=>[]};
 const ctx={document:docStub,window:{addEventListener:noop},URL,URLSearchParams,Date,JSON,
  fetch:async(url)=>{const value=responses.get(String(url).split("?")[0]);return value===undefined?
   {status:404,ok:false}:{status:200,ok:true,json:async()=>value}},
  console};
 ctx.globalThis=ctx;
 vm.runInNewContext(executable,ctx,{timeout:2000});
 return ctx.__queueTests.classify;
}

test("new ready draft requires an actual owner text decision",async()=>{
 assert.equal((await model()(doc)).group,"review");
 assert.equal((await model()(doc)).label,"Проверить текст");
});
test("drafting and blocked are not falsely marked ready for chief editor review",async()=>{
 assert.equal((await model()({...doc,status:"drafting"})).group,"active");
 assert.equal((await model()({...doc,status:"blocked"})).group,"error");
});
test("approved text without a candidate is in progress with artist",async()=>{
 const cls=model({["auto_decisions/"+key+".json"]:textDecision});
 assert.equal((await cls(doc)).group,"active");
});
test("an unreviewed image requires owner decision",async()=>{
 const cls=model({["auto_decisions/"+key+".json"]:textDecision,["auto_covers/"+key+"-v1.json"]:cover(1)});
 const status=await cls(doc);
 assert.equal(status.group,"review");assert.match(status.label,/обложку v1/);
});
test("approved cover still awaiting transfer is not completed",async()=>{
 const cls=model({
  ["auto_decisions/"+key+".json"]:textDecision,
  ["auto_covers/"+key+"-v1.json"]:cover(1),
  ["auto_cover_decisions/"+key+"-v1.json"]:coverDecision(1,"approve_cover","cover_approved_handoff_pending")
 });
 const status=await cls(doc);
 assert.equal(status.group,"transfer");assert.match(status.label,/ждёт передачи/);
});
test("handoff confirmed in GitHub moves material to completed",async()=>{
 const cls=model({
  ["auto_decisions/"+key+".json"]:textDecision,
  ["auto_covers/"+key+"-v1.json"]:cover(1),
  ["auto_cover_decisions/"+key+"-v1.json"]:coverDecision(1,"approve_cover","cover_approved_handoff_pending"),
  ["auto_handoffs/"+key+"-v1.json"]:handoff(1)
 });
 const status=await cls(doc);
 assert.equal(status.group,"done");assert.equal(status.label,"Передано в очередь сайта");
});
test("rejected cover v1 followed by approved v2 is a transfer, not a repeat review",async()=>{
 const cls=model({
  ["auto_decisions/"+key+".json"]:textDecision,
  ["auto_covers/"+key+"-v1.json"]:cover(1),
  ["auto_cover_decisions/"+key+"-v1.json"]:coverDecision(1,"revise_cover","cover_revision_requested"),
  ["auto_covers/"+key+"-v2.json"]:cover(2),
  ["auto_cover_decisions/"+key+"-v2.json"]:coverDecision(2,"approve_cover","cover_approved_handoff_pending")
 });
 const status=await cls(doc);assert.equal(status.group,"transfer");assert.match(status.label,/v2/);
});
test("mismatched approval version is never treated as safe success",async()=>{
 const cls=model({
  ["auto_decisions/"+key+".json"]:textDecision,
  ["auto_covers/"+key+"-v1.json"]:cover(1),
  ["auto_cover_decisions/"+key+"-v1.json"]:coverDecision(2,"approve_cover","cover_approved_handoff_pending")
 });
 await assert.rejects(cls(doc),/не совпадает/);
});
test("rejected text is not shown as awaiting approval",async()=>{
 const cls=model({["auto_decisions/"+key+".json"]:{...textDecision,status:"rejected",action:"reject"}});
 assert.equal((await cls(doc)).group,"done");
});
