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
  const layout=()=>evaluate('(()=>{if(document.readyState!=="complete")return null;const card=document.querySelector(".r2 .row");if(!card)return null;const r=card.getBoundingClientRect(),im=card.querySelector("img").getBoundingClientRect(),copy=card.querySelector(".copy").getBoundingClientRect(),time=card.querySelector(".time").getBoundingClientRect();return {url:location.href,viewport:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth,card:r.width,img:im.width,ib:im.bottom,ct:copy.top,cw:copy.width,time:time.top,title:parseFloat(getComputedStyle(card.querySelector("h3")).fontSize),radius:parseFloat(getComputedStyle(card).borderTopLeftRadius),dates:document.querySelectorAll(".day-title").length,columns:getComputedStyle(card).gridTemplateColumns.split(" ").length}})()');
  async function check(rubric,width){
    await call("Emulation.setDeviceMetricsOverride",{width,height:844,deviceScaleFactor:1,mobile:false});
    const url=pathToFileURL(resolve("lab/design/rubrics/r2/"+rubric+"/index.html")).href;
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
  assert.ok(!desktop.overflow&&desktop.columns===4&&Math.abs(desktop.img-156)<=2&&desktop.title===17,"original desktop R2");
  console.log("PASS: all five R2 rubrics on phones, tablet and unchanged desktop");
}finally{
  ws?.close();
  chrome.kill();
  await sleep(250);
  await rm(profile,{recursive:true,force:true,maxRetries:5,retryDelay:100});
}
