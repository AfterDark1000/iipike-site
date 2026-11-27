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

  const inspect=()=>evaluate(`(()=>{if(document.readyState!=="complete")return null;const main=document.querySelector("main.wrap"),title=main?.querySelector(".article-title"),cover=main?.querySelector(".cover"),body=main?.querySelector(".article-body"),article=body?.querySelector(".article-text");if(!title||!cover||!article)return null;const r=e=>{const q=e.getBoundingClientRect();return {x:q.x,y:q.y,right:q.right,bottom:q.bottom,w:q.width}};const rail=body.querySelector(".article-a4-rail,.sources"),table=article.querySelector(".editorial-table-scroll"),toc=body.querySelector(".article-a4-toc");return {url:location.href,width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth,overflowElements:[...document.querySelectorAll("body *")].filter(e=>{const r=e.getBoundingClientRect();return r.right>innerWidth+1&&!e.closest(".editorial-table-scroll,.editorial-carousel-track")}).slice(0,12).map(e=>({tag:e.tagName,cls:String(e.className),right:e.getBoundingClientRect().right})),main:r(main),title:r(title),cover:r(cover),body:r(article),rail:rail?r(rail):null,background:getComputedStyle(main).backgroundColor,grid:getComputedStyle(main).display,font:getComputedStyle(article).fontFamily,titleFont:getComputedStyle(title.querySelector("h1")).fontFamily,coverFit:getComputedStyle(cover.querySelector("img")).objectFit,toc:toc?toc.querySelectorAll("a").length:0,headings:article.querySelectorAll(":scope > h2").length,tableFits:!table||table.clientWidth<=article.clientWidth+1,tableScroll:table?table.scrollWidth>table.clientWidth:false}})()`);
  async function check(slug,width){
    await call("Emulation.setDeviceMetricsOverride",{width,height:844,deviceScaleFactor:1,mobile:false});
    const url=pathToFileURL(resolve("articles/"+slug+"/index.html")).href;
    await call("Page.navigate",{url});
    const s=await until("A4 "+slug+" at "+width,async()=>{const a=await inspect();return a?.url===url&&a.width===width?a:null});
    console.log(slug,width,s);
    assert.equal(s.grid,"grid");assert.equal(s.background,"rgb(255, 253, 248)");
    assert.match(s.font,/system-ui/);assert.match(s.titleFont,/system-ui/);assert.equal(s.coverFit,"contain");
    assert.ok(!s.overflow&&s.tableFits,"no page-wide overflow");
    if(s.headings>=2)assert.equal(s.toc,s.headings,"complete real TOC");
    if(width>900){assert.ok(s.title.right<=s.cover.x+1&&s.body.y>=Math.max(s.cover.bottom,s.title.bottom),"split hero above body");if(s.rail)assert.ok(s.body.right<=s.rail.x+1,"right rail")}
    else{assert.ok(s.cover.y>=s.title.bottom&&s.body.y>=s.cover.bottom,"mobile stacked hero");if(s.rail)assert.ok(s.rail.y>=s.body.bottom-1,"mobile rail below text")}
    if(slug==="sber-gigachat-4-20261126"&&width<600)assert.ok(s.tableScroll,"table scrolls locally");
  }
  for(const slug of ["sber-gigachat-4-20261126","google-search-ai-links","openai-gpt-7-rumors-investigation-20261125"]){await check(slug,1440);await check(slug,390)}
  await check("sber-gigachat-4-20261126",320);
  console.log("PASS: published A4 + A6 article layouts");
}finally{
  ws?.close();chrome.kill();await sleep(250);await rm(profile,{recursive:true,force:true,maxRetries:5,retryDelay:100});
}
