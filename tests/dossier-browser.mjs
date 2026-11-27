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
  await call("Emulation.setDeviceMetricsOverride",{width:390,height:844,deviceScaleFactor:1,mobile:false});
  await call("Emulation.setEmulatedMedia",{features:[{name:"prefers-reduced-motion",value:"reduce"}]});
  await call("Page.navigate",{url:pathToFileURL(resolve(process.argv[2])).href});
  const stateExpr=String.raw`(()=>{
    const g=document.getElementById("dossier");
    if(!g)return null;
    const t=g.querySelector(".dossier-showcase");
    return {visible:!g.querySelector(".dossier-controls").hidden,
      count:g.querySelector(".dossier-count").textContent,
      prev:g.querySelector("[data-dossier-prev]").disabled,
      next:g.querySelector("[data-dossier-next]").disabled,
      left:t.scrollLeft, width:t.clientWidth, total:t.scrollWidth,
      page:document.documentElement.scrollWidth,viewport:innerWidth,active:Array.from(g.querySelectorAll(".dossier-thumb")).findIndex(a=>a.getAttribute("aria-current")==="true"),n:g.querySelectorAll(".dossier-slide").length};
  })()`;
  const state=()=>evaluate(stateExpr);
  await until("gallery initialized",async()=>{const s=await state();return s?.visible?s:null});
  let s=await state();
  console.log("initial",s);
  assert.ok(s.n>=2);const n=s.n;assert.equal(s.count,"1 / "+n);assert.equal(s.prev,true);assert.equal(s.next,false);
  assert.ok(s.total>s.width && s.page<=s.viewport,"gallery must not widen the article");
  await evaluate('document.querySelector("[data-dossier-next]").click()');
  async function expectFrame(number){
    const expected=number+" / "+n;
    let last;
    try{
      await until("frame "+number,async()=>{
        last=await state();
        return last?.count===expected && Math.abs(last.left-(number-1)*last.width)<=2 &&
          last.prev===(number===1)&&last.next===(number===n)&&last.active===number-1?last:null;
      },5000);
    }catch(e){throw Error(e.message+"; last state "+JSON.stringify(last))}
    console.log("frame",number,last);
  }
  await expectFrame(2);
  await evaluate('document.querySelectorAll(".dossier-thumb")[0].click()');
  await expectFrame(1);
  await evaluate('document.querySelectorAll(".dossier-thumb")[1].click()');
  await expectFrame(2);
  await evaluate('document.querySelector(".dossier-showcase").dispatchEvent(new KeyboardEvent("keydown",{key:"Home",bubbles:true}))');
  await expectFrame(1);
  // Verify native scroll independently of buttons/keyboard.
  await evaluate('(()=>{const t=document.querySelector(".dossier-showcase");t.scrollLeft=t.scrollWidth;})()');
  await expectFrame(n);
  await evaluate('document.querySelector("[data-dossier-prev]").click()');
  await expectFrame(n-1);
  console.log("PASS: Dossier manual navigation at 390px");
  await call("Emulation.setDeviceMetricsOverride",{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  await until("desktop layout",async()=>{const v=await state();return v?.viewport===1440?v:null});
  await evaluate('document.querySelectorAll(".dossier-thumb")[0].click()');
  await expectFrame(1);
  const desktop=await evaluate('(()=>{const g=document.getElementById("dossier");return {height:g.offsetHeight,cover:g.querySelector(".dossier-card-art").offsetHeight,wide:document.documentElement.scrollWidth>innerWidth}})()');
  console.log("desktop showcase",desktop);
  assert.ok(desktop.height<500&&!desktop.wide,"desktop showcase must be compact");
  await call("Page.navigate",{url:pathToFileURL(resolve(process.argv[3])).href});
  const archiveExpr='(()=>{const g=document.querySelector(".dossier-archive .dossier-grid");if(!g)return null;const cards=Array.from(g.querySelectorAll(".dossier-card"));return {n:cards.length,columns:getComputedStyle(g).gridTemplateColumns.split(" ").length,empty:cards.map(c=>{const art=c.querySelector(".dossier-card-art");return Math.abs(art.clientHeight-art.querySelector("img").clientHeight)})}})()';
  await until("archive document and stylesheet loaded",async()=>evaluate('document.readyState==="complete" && !!document.querySelector(".dossier-archive .dossier-grid")'));
  const archive=await evaluate(archiveExpr);
  console.log("archive desktop",archive);
  assert.ok(archive.n>=2&&archive.columns===2&&archive.empty.every(x=>x<=2),"archive images must not have empty bands");
  await call("Emulation.setDeviceMetricsOverride",{width:390,height:844,deviceScaleFactor:1,mobile:false});
  await until("archive mobile layout",async()=>{const v=await evaluate(archiveExpr);return v?.columns===1&&v.empty.every(x=>x<=2)?v:null});
  console.log("PASS: archive responsive grid");
}finally{
  ws?.close();
  chrome.kill();
  await sleep(250);
  await rm(profile,{recursive:true,force:true,maxRetries:5,retryDelay:100});
}
