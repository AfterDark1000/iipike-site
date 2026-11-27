// Test actual browser layout and scroll events in real time, not --dump-dom's
// virtual clock, which can advance timers before the compositor scrolls.
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {mkdtemp,readFile,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join,resolve} from "node:path";
import {pathToFileURL} from "node:url";
import {setTimeout as sleep} from "node:timers/promises";

const profile=await mkdtemp(join(tmpdir(),"hpii-dossier-"));
const chrome=spawn("google-chrome",["--headless","--no-sandbox","--disable-dev-shm-usage",
  "--disable-background-networking","--allow-file-access-from-files",
  "--remote-debugging-port=0","--user-data-dir="+profile,"about:blank"],
  {stdio:["ignore","ignore","ignore"]});
let ws;
async function until(label,probe,timeout=15000){
  const end=Date.now()+timeout;
  let last;
  while(Date.now()<end){
    last=await probe();
    if(last)return last;
    await sleep(80);
  }
  throw Error(label+" timed out");
}
try{
  const port=await until("Chrome debugging port",async()=>{
    try{return (await readFile(join(profile,"DevToolsActivePort"),"utf8")).split("\n")[0]}catch{return null}
  });
  const target=await until("Chrome page target",async()=>{
    try{return (await (await fetch("http://127.0.0.1:"+port+"/json/list")).json()).find(x=>x.type==="page")}catch{return null}
  });
  ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,bad)=>{ws.addEventListener("open",ok,{once:true});ws.addEventListener("error",bad,{once:true})});
  let serial=0;
  const pending=new Map();
  ws.addEventListener("message",event=>{
    const msg=JSON.parse(event.data),job=pending.get(msg.id);
    if(!job)return;
    pending.delete(msg.id);clearTimeout(job.timer);
    if(msg.error)job.reject(Error(JSON.stringify(msg.error)));else job.resolve(msg.result);
  });
  function call(method,params={}){
    return new Promise((resolve,reject)=>{
      const id=++serial;
      const timer=setTimeout(()=>{pending.delete(id);reject(Error("CDP timeout: "+method))},10000);
      pending.set(id,{resolve,reject,timer});
      ws.send(JSON.stringify({id,method,params}));
    });
  }
  async function evaluate(expression){
    const r=await call("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));
    return r.result.value;
  }
  await call("Network.enable");
  await call("Network.setBlockedURLs",{urls:["http://*","https://*"]});
  const layout=()=>evaluate('(()=>{if(document.readyState!=="complete")return null;const card=document.querySelector(".rubric-r2 .archive-card");if(!card)return null;const r=card.getBoundingClientRect(),im=card.querySelector("img").getBoundingClientRect(),copy=card.querySelector(".rubric-copy").getBoundingClientRect(),time=card.querySelector(".rubric-time").getBoundingClientRect();return {url:location.href,viewport:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth,card:r.width,img:im.width,ib:im.bottom,ct:copy.top,cw:copy.width,time:time.top,title:parseFloat(getComputedStyle(card.querySelector("h3")).fontSize),radius:parseFloat(getComputedStyle(card).borderTopLeftRadius),dates:document.querySelectorAll(".rubric-day-title").length,columns:getComputedStyle(card).gridTemplateColumns.split(" ").length}})()');
  async function check(rubric,width){
    await call("Emulation.setDeviceMetricsOverride",{width,height:844,deviceScaleFactor:1,mobile:false});
    const url=pathToFileURL(resolve(rubric==="archive"?"articles/index.html":(rubric.startsWith("entities/")||rubric.startsWith("topics/"))?rubric+"/index.html":"rubrics/"+rubric+"/index.html")).href;
    await call("Page.navigate",{url});
    return until("R2 "+rubric+" at "+width,async()=>{const s=await layout();return s?.url===url&&s.viewport===width?s:null});
  }
  for(const rubric of ["news","skynet","what-are-you-doing","quotes","made-with-ai"]){
    const s=await check(rubric,390);
    console.log(rubric,s);
    assert.ok(!s.overflow&&s.dates>0&&s.columns===1&&s.img>=s.card-3&&s.img>=320&&s.ct>=s.ib&&s.title>=19&&s.radius>=8,"full-width readable mobile card");
  }
  const tiny=await check("skynet",320);
  console.log("small phone",tiny);
  assert.ok(!tiny.overflow&&tiny.img>=tiny.card-3&&tiny.img>=275&&tiny.ct>=tiny.ib,"small phone fits including scrollbar");
  const tablet=await check("skynet",650);
  console.log("tablet",tablet);
  assert.ok(!tablet.overflow&&tablet.columns===2&&tablet.img>200,"compact tablet row");
  const desktop=await check("skynet",1440);
  console.log("desktop",desktop);
  assert.ok(!desktop.overflow&&desktop.columns===4&&Math.abs(desktop.img-156)<=2&&desktop.title===17,"approved desktop R2");
  for(const width of [320,390,650,1440]){
    const a=await check("archive",width);
    console.log("all articles archive",width,a);
    assert.ok(!a.overflow&&a.dates>0,"archive fits viewport");
    const labels=await evaluate('Array.from(document.querySelectorAll(".archive-r2 .archive-card")).every(c=>c.querySelector(".archive-rubric")?.textContent.trim())');
    assert.ok(labels,"every article has a rubric label");
    if(width<=540)assert.ok(a.columns===1&&a.img>=a.card-3&&a.ct>=a.ib,"archive mobile full-width cover");
    else if(width<=700)assert.equal(a.columns,2);
    else assert.ok(a.columns===4&&Math.abs(a.img-156)<=2,"archive desktop R2");
  }
  for(const page of ["entities/companies/openai","entities/products/chatgpt","topics/ai-in-russia","topics/agents"]){
    for(const width of [320,390,650,1440]){
      const s=await check(page,width);
      console.log(page,width,s);
      assert.ok(!s.overflow&&s.dates>0,"entity R2 fits viewport");
      if(width<=540)assert.ok(s.columns===1&&s.img>=s.card-3&&s.ct>=s.ib,"entity mobile cover");
      else if(width<=700)assert.equal(s.columns,2);
      else assert.ok(s.columns===4&&Math.abs(s.img-156)<=2,"entity desktop R2");
    }
  }
  for(const width of [320,390,650,1440]){
    await call("Emulation.setDeviceMetricsOverride",{width,height:844,deviceScaleFactor:1,mobile:false});
    const url=pathToFileURL(resolve("topics/index.html")).href;
    await call("Page.navigate",{url});
    const s=await until("topic directory",async()=>{
      const result=await evaluate('(()=>{const g=document.querySelector(".topic-r2 .topic-index-grid");if(document.readyState!=="complete"||!g)return null;return {url:location.href,width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth,columns:getComputedStyle(g).gridTemplateColumns.split(" ").length,tiles:g.querySelectorAll(".topic-index-link").length}})()');
      return result?.url===url&&result.width===width?result:null;
    });
    assert.ok(!s.overflow&&s.tiles>0,"topic directory fits");
    assert.equal(s.columns,width<=560?1:width<=900?2:3);
  }
  console.log("PASS: rubrics, archive, entities and topic R2 layouts");
}finally{
  ws?.close();
  chrome.kill();
  await sleep(250);
  await rm(profile,{recursive:true,force:true,maxRetries:5,retryDelay:100});
}
