// Test actual browser layout and scroll events in real time, not --dump-dom's
// virtual clock, which can advance timers before the compositor scrolls.
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {mkdtemp,readFile,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join,resolve} from "node:path";
import {pathToFileURL} from "node:url";
import {setTimeout as sleep} from "node:timers/promises";

const profile=await mkdtemp(join(tmpdir(),"hpii-carousel-"));
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
    const g=document.querySelector(".editorial-carousel");
    if(!g)return null;
    const t=g.querySelector(".editorial-carousel-track");
    return {visible:!g.querySelector(".editorial-carousel-controls").hidden,
      count:g.querySelector(".editorial-carousel-count").textContent,
      prev:g.querySelector("[data-carousel-prev]").disabled,
      next:g.querySelector("[data-carousel-next]").disabled,
      left:t.scrollLeft, width:t.clientWidth, total:t.scrollWidth,
      page:document.documentElement.scrollWidth,viewport:innerWidth};
  })()`;
  const state=()=>evaluate(stateExpr);
  await until("gallery initialized",async()=>{const s=await state();return s?.visible?s:null});
  let s=await state();
  console.log("initial",s);
  assert.equal(s.count,"1 / 2");assert.equal(s.prev,true);assert.equal(s.next,false);
  assert.ok(s.total>s.width && s.page<=s.viewport,"gallery must not widen the article");
  await evaluate('document.querySelector("[data-carousel-next]").click()');
  async function expectFrame(number){
    const expected=number+" / 2";
    let last;
    try{
      await until("frame "+number,async()=>{
        last=await state();
        return last?.count===expected && Math.abs(last.left-(number-1)*last.width)<=2 &&
          last.prev===(number===1)&&last.next===(number===2)?last:null;
      },5000);
    }catch(e){throw Error(e.message+"; last state "+JSON.stringify(last))}
    console.log("frame",number,last);
  }
  await expectFrame(2);
  await evaluate('document.querySelector(".editorial-carousel-track").dispatchEvent(new KeyboardEvent("keydown",{key:"Home",bubbles:true}))');
  await expectFrame(1);
  // Verify native scroll independently of buttons/keyboard.
  await evaluate('(()=>{const t=document.querySelector(".editorial-carousel-track");t.scrollLeft=t.scrollWidth;})()');
  await expectFrame(2);
  await evaluate('document.querySelector("[data-carousel-prev]").click()');
  await expectFrame(1);
  console.log("PASS: actual carousel layout, buttons, keyboard, native scroll at 390px");
}finally{
  ws?.close();
  chrome.kill();
  await sleep(250);
  await rm(profile,{recursive:true,force:true,maxRetries:5,retryDelay:100});
}
