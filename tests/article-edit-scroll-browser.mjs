// Test actual browser layout and scroll events in real time, not --dump-dom's
// virtual clock, which can advance timers before the compositor scrolls.
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {mkdtemp,readFile,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join,resolve} from "node:path";
import {createServer} from "node:http";
import {setTimeout as sleep} from "node:timers/promises";

const source=Array.from({length:32},(_,i)=>"Контрольный абзац "+(i+1)+". "+"Длинный текст для проверки переноса строк и сопоставления абзацев. ".repeat(6)).join("\n\n");
const body=source.replace("Контрольный абзац 7.","![Проверочное изображение](illustrations/fixture/tall.svg)\n\nКонтрольный абзац 7.").replace("Контрольный абзац 9.","| Модель | Цена |\n| --- | ---: |\n| A | 10 |\n| B | 20 |\n\nКонтрольный абзац 9.").replace("tall.svg","tall.png");
const fixture={ok:true,id:"fixture",title:"Проверка редактора",cover:"assets/test.png",markdown:body,original:body,base_sha:"a".repeat(40),pending:false,dzen_published:false};
const server=createServer(async(req,res)=>{
 const path=new URL(req.url,"http://localhost").pathname;
 try{
  if(path==="/admin/auth/gate.js"){
   res.setHeader("content-type","application/javascript");
   res.end("window.HpiiAdminAuth={fetchApi:async()=>"+JSON.stringify(fixture)+"};document.documentElement.classList.add('hpii-authorized');window.dispatchEvent(new CustomEvent('hpii-admin-authorized'));");
  }else if(path.endsWith(".png")){
   res.setHeader("content-type","image/svg+xml");res.end('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="1000"><rect width="600" height="1000" fill="#a5b29f"/></svg>');
  }else if(["/admin/article-edit/","/admin/article-edit/app.js","/admin/dzen-tables.js"].includes(path)){
   res.setHeader("content-type",path.endsWith(".js")?"application/javascript":"text/html; charset=utf-8");
   res.end(await readFile(resolve("."+path+(path.endsWith("/")?"index.html":""))));
  }else{res.statusCode=404;res.end()}
 }catch(e){res.statusCode=500;res.end(String(e))}
});
await new Promise(ok=>server.listen(0,"127.0.0.1",ok));
const base="http://127.0.0.1:"+server.address().port;
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
  await call("Emulation.setDeviceMetricsOverride",{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  await call("Page.navigate",{url:base+"/admin/article-edit/?id=fixture"});
  const snapshot=()=>evaluate('(()=>{const l=document.getElementById("body"),r=document.getElementById("previewPane");if(!l||!r||document.getElementById("editor").hidden)return null;return {lt:l.getBoundingClientRect().top,rt:r.getBoundingClientRect().top,lh:l.clientHeight,rh:r.clientHeight,l:l.scrollTop,r:r.scrollTop,lmax:l.scrollHeight-l.clientHeight,rmax:r.scrollHeight-r.clientHeight,blocks:document.querySelectorAll("#preview > *").length}})()');
  let s=await until("editor loaded",async()=>{const v=await snapshot();return v?.blocks>20&&v.lmax>0&&v.rmax>0?v:null});
  assert.ok(Math.abs(s.lt-s.rt)<=1&&Math.abs(s.lh-s.rh)<=2,"same top and viewport height");
  assert.equal(s.l,0);assert.equal(s.r,0);
  await evaluate('document.getElementById("body").scrollTop=600');
  s=await until("left scroll drives right",async()=>{const v=await snapshot();return v.r>50?v:null});
  console.log("left drives right",s);
  const before=s.l;
  await evaluate('document.getElementById("previewPane").scrollTop+=500');
  s=await until("right scroll drives left",async()=>{const v=await snapshot();return Math.abs(v.l-before)>50?v:null});
  console.log("right drives left",s);
  // Jump to the source marker of a known paragraph, and verify its rendered
  // partner is near the viewport top even with a tall image in between.
  await evaluate('(()=>{const l=document.getElementById("body"),m=document.getElementById("sourceMirror"),p=Array.from(document.querySelectorAll("#preview > *"));const i=p.findIndex(x=>x.textContent.startsWith("Контрольный абзац 12."));const a=m.querySelectorAll("span")[i];l.scrollTop=a.getBoundingClientRect().top-m.getBoundingClientRect().top-parseFloat(getComputedStyle(l).paddingTop)})()');
  await until("paragraph correspondence",async()=>evaluate('(()=>{const p=Array.from(document.querySelectorAll("#preview > *")).find(x=>x.textContent.startsWith("Контрольный абзац 12."));const r=document.getElementById("previewPane");return Math.abs(p.getBoundingClientRect().top-r.getBoundingClientRect().top-16)<35})()'));
  await evaluate('(()=>{const l=document.getElementById("body");l.scrollTop=l.scrollHeight})()');
  await until("both at bottom",async()=>{const v=await snapshot();return Math.abs(v.r-v.rmax)<3&&Math.abs(v.l-v.lmax)<3?v:null});
  await evaluate('document.getElementById("syncScroll").click()');
  s=await snapshot();const hold=s.r;
  await evaluate('document.getElementById("body").scrollTop=0');
  await sleep(300);s=await snapshot();assert.equal(s.l,0);assert.equal(s.r,hold);
  await evaluate('document.getElementById("syncScroll").click()');
  await until("sync restored",async()=>{const v=await snapshot();return v.r<3?v:null});
  await call("Emulation.setDeviceMetricsOverride",{width:390,height:844,deviceScaleFactor:1,mobile:false});
  await until("mobile stacked",async()=>{const v=await snapshot();return v.rt>v.lt+v.lh-3?v:null});
  console.log("PASS: aligned pane heights, bidirectional paragraph mapping, end, toggle, mobile");
}finally{
  ws?.close();chrome.kill();server.close();
  await sleep(250);
  await rm(profile,{recursive:true,force:true,maxRetries:5,retryDelay:100});
}
