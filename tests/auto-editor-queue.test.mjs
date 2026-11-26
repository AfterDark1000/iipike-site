import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const html=fs.readFileSync(new URL("../admin/auto-editor/index.html",import.meta.url),"utf8");
const script=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)?.[1];
assert.ok(script,"Inline auto-editor script must exist");
const executable=script.replace(/\}\)\(\);\s*$/, "globalThis.__queueTests={classify,fetchGitHubRecord,readPublishedIds,queueRows,archiveSlice};})();");
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
function model(attachments={},apiAttachments={},newsRows=null){
 const responses=new Map(Object.entries(attachments).map(([p,value])=>[raw+p,value]));
 const authoritative=new Map(Object.entries(apiAttachments));
 const noop=()=>{};
 const docStub={getElementById:()=>({addEventListener:noop}),querySelectorAll:()=>[]};
 const ctx={document:docStub,window:{
  addEventListener:noop,
  HpiiAdminAuth:{
   readEditorialRecord:async path=>{
    const value=authoritative.get(path);
    if(value==="rate_limited")throw Error("editorial_record_unavailable");
    return value===undefined?{found:false}:{found:true,record:value};
   }
  }
 },URL,URLSearchParams,Date,JSON,atob,TextDecoder,
  fetch:async(url)=>{
   const key=String(url).split("?")[0];
   if(key==="https://raw.githubusercontent.com/AfterDark1000/iipike-site/main/news.json"){
    return newsRows===null?{status:404,ok:false}:{status:200,ok:true,json:async()=>newsRows};
   }
   const value=responses.get(key);
   return value===undefined?{status:404,ok:false}:{status:200,ok:true,json:async()=>value}
  },
  console};
 ctx.globalThis=ctx;
 vm.runInNewContext(executable,ctx,{timeout:2000});
 const classify=(draft,published=[])=>ctx.__queueTests.classify(draft,new Set(published));
 classify.readPublishedIds=ctx.__queueTests.readPublishedIds;
 classify.queueRows=ctx.__queueTests.queueRows;
 classify.archiveSlice=ctx.__queueTests.archiveSlice;
 return classify;
}

test("new ready draft requires an actual owner text decision",async()=>{
 assert.equal((await model()(doc)).group,"review");
 assert.equal((await model()(doc)).label,"Проверить текст");
});
test("parallel approvals distinguish both open, cover first and text still needed",async()=>{
 const base={["auto_covers/"+key+"-v1.json"]:cover(1)};
 assert.match((await model(base)(doc)).label,/текст и обложку/);
 const cls=model({...base,["auto_cover_decisions/"+key+"-v1.json"]:coverDecision(1,"approve_cover","cover_approved_handoff_pending")});
 const state=await cls(doc);assert.equal(state.group,"review");assert.match(state.label,/проверить текст/);
});
test("refresh is above growing list",()=>{
 assert.ok(html.indexOf('id="reload"')<html.indexOf('id="list"'));
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
 assert.equal(status.group,"transfer");assert.match(status.label,/передача не подтверждена/);
});
test("handoff confirmed but not published remains in site queue",async()=>{
 const cls=model({
  ["auto_decisions/"+key+".json"]:textDecision,
  ["auto_covers/"+key+"-v1.json"]:cover(1),
  ["auto_cover_decisions/"+key+"-v1.json"]:coverDecision(1,"approve_cover","cover_approved_handoff_pending"),
  ["auto_handoffs/"+key+"-v1.json"]:handoff(1)
 });
 const status=await cls(doc);
 assert.equal(status.group,"transfer");assert.equal(status.label,"В очереди сайта");
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

test("fresh approved cover is recovered through the authenticated gateway when raw.githubusercontent returns stale 404",async()=>{
 const accepted=model(
  {["auto_decisions/"+key+".json"]:textDecision,
   ["auto_covers/"+key+"-v1.json"]:cover(1)},
  {["editorial_inbox/auto_cover_decisions/"+key+"-v1.json"]:
   coverDecision(1,"approve_cover","cover_approved_handoff_pending")}
 );
 const status=await accepted(doc);
 assert.equal(status.group,"transfer");
 assert.match(status.label,/утверждена/);
});
test("an authenticated GitHub read outage never becomes a false 'not approved' status",async()=>{
 const classify=model(
  {["auto_decisions/"+key+".json"]:textDecision,
   ["auto_covers/"+key+"-v1.json"]:cover(1)},
  {["editorial_inbox/auto_cover_decisions/"+key+"-v1.json"]:"rate_limited"}
 );
 await assert.rejects(classify(doc),/editorial_record_unavailable/);
});
test("fresh text approval is also recovered from the authenticated gateway",async()=>{
 const classify=model({},{
  ["editorial_inbox/auto_decisions/"+key+".json"]:textDecision
 });
 const result=await classify(doc);
 assert.equal(result.group,"active");
 assert.equal(result.label,"Текст утверждён · у художника");
});

test("main/news.json confirmed publication overrides waiting handoff display",async()=>{
 const cls=model({
  ["auto_decisions/"+key+".json"]:textDecision,
  ["auto_covers/"+key+"-v1.json"]:cover(1),
  ["auto_cover_decisions/"+key+"-v1.json"]:coverDecision(1,"approve_cover","cover_approved_handoff_pending")
 });
 const status=await cls(doc,[slug]);
 assert.equal(status.group,"done");
 assert.equal(status.label,"Опубликовано на сайте");
});
test("published status is only claimed when main news.json contains matching published article",async()=>{
 const cls=model({}, {},[
  {id:slug,url:"articles/"+slug+"/",published_at_utc:"2026-11-18T18:15:41Z"},
  {id:"not-published",url:"articles/not-published/"}
 ]);
 const ids=await cls.readPublishedIds();
 assert.equal(ids.has(slug),true);
 assert.equal(ids.has("not-published"),false);
});
test("handoff and verified publication means completed, not still in queue",async()=>{
 const cls=model({
  ["auto_decisions/"+key+".json"]:textDecision,
  ["auto_covers/"+key+"-v1.json"]:cover(1),
  ["auto_cover_decisions/"+key+"-v1.json"]:coverDecision(1,"approve_cover","cover_approved_handoff_pending"),
  ["auto_handoffs/"+key+"-v1.json"]:handoff(1)
 });
 const status=await cls(doc,[slug]);
 assert.equal(status.group,"done");
 assert.equal(status.label,"Опубликовано на сайте");
});

test("working view keeps pending transfers and errors but excludes completed archive",()=>{
 const m=model();
 const rows=["done","transfer","active","review","error"].map((group,i)=>({group,name:"id-"+i,title:"Статья "+i,doc:{pool_sequence:i}}));
 assert.equal(Array.from(m.queueRows(rows,"all"),x=>x.group).join(","),"review,error,active,transfer");
 assert.equal(Array.from(m.queueRows(rows,"done"),x=>x.group).join(","),"done");
});
test("archive search reaches every completed row; pages contain at most 20 and newest pool sequence first",()=>{
 const m=model();
 const rows=Array.from({length:53},(_,i)=>({group:"done",name:"id-"+(i+1),title:"Архив "+(i+1),doc:{pool_sequence:i+1}}));
 const ordered=m.queueRows(rows,"done");
 const first=m.archiveSlice(ordered,0), last=m.archiveSlice(ordered,99);
 assert.equal(first.total,53);assert.equal(first.pages,3);assert.equal(first.rows.length,20);
 assert.equal(first.rows[0].doc.pool_sequence,53);
 assert.equal(last.page,2);assert.equal(last.rows.length,13);
 assert.equal(last.rows.at(-1).doc.pool_sequence,1);
 assert.equal(m.queueRows(rows,"done","Архив 1").some(x=>x.name==="id-1"),true);
 assert.equal(m.archiveSlice([],9).rows.length,0);
});
test("each queue stage has a distinct visual color and archive is a separate view",()=>{
 for(const stage of ["review","error","active","transfer","done"])assert.ok(html.includes('[data-stage="'+stage+'"]'));
 assert.ok(html.includes('data-view="all" aria-pressed="true">Рабочие'));
 assert.ok(html.includes('data-view="done"'));
});
