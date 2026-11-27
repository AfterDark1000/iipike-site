(function(){
"use strict";
const $=id=>document.getElementById(id);
const id=new URLSearchParams(location.search).get("id");
const validId=x=>typeof x==="string"&&/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(x)&&x.length<=72;
let state=null,busy=false,dirty=false,rows=[],version=0;
function node(tag,value){const e=document.createElement(tag);if(value!==undefined)e.textContent=value;return e}
function status(value,error=false){$("status").textContent=value;$("status").classList.toggle("error",error)}
function setDirty(){dirty=!!state&&$("body").value!==state.markdown;controls()}
function controls(){
 $("body").disabled=!state||busy||state.pending;
 $("save").disabled=!state||busy||state.pending||!dirty;
 $("reload").disabled=busy;
 $("restore").disabled=!state||busy||state.pending;
 for(const b of document.querySelectorAll("[data-wrap],#paragraph,#heading"))b.disabled=$("body").disabled;
 $("saveHint").textContent=state?.pending?"Правка в обработке. Старая статья пока сохранена.":dirty?"Есть несохранённые изменения":"";
}
function inline(parent,value){
 const re=/\[([^\]\n]+)\]\((https:\/\/[^)\s]+)\)|\*\*([^*\n]+)\*\*|\*([^*\n]+)\*/g;
 let last=0,m;
 while((m=re.exec(value))){
  parent.append(document.createTextNode(value.slice(last,m.index)));
  if(m[1]!==undefined){
   let safe=false;try{const u=new URL(m[2]);safe=u.protocol==="https:"&&!u.username&&!u.password&&(!u.port||u.port==="443")}catch(_){}
   if(safe){const a=node("a",m[1]);a.href=m[2];a.target="_blank";a.rel="noopener noreferrer";parent.append(a)}
   else parent.append(document.createTextNode(m[0]));
  }else parent.append(node(m[3]!==undefined?"strong":"em",m[3]??m[4]));
  last=re.lastIndex;
 }
 parent.append(document.createTextNode(value.slice(last)));
}
// The textarea's invisible mirror uses its real wrap width and typography.
// Match source character offsets to rendered block offsets, rather than
// assuming a photo, table or heading has the same height in both columns.
const left=$("body"),right=$("previewPane"),mirror=$("sourceMirror"),sync=$("syncScroll");
let anchors=[],mapping=[],expected=new WeakMap(),active=left,refreshFrame=0;
function enabled(){return sync.checked&&matchMedia("(min-width:851px)").matches&&!!state&&!$("editor").hidden}
function measure(){
 if(!enabled()||!left.clientWidth||!right.clientHeight){mapping=[];return}
 const style=getComputedStyle(left);
 for(const k of ["font","lineHeight","letterSpacing","wordSpacing","tabSize","padding","whiteSpace","overflowWrap","wordBreak","textAlign","textIndent"])mirror.style[k]=style[k];
 mirror.style.width=left.clientWidth+"px";
 mirror.replaceChildren();
 let last=0;const spans=[];
 for(const anchor of anchors){
  mirror.append(document.createTextNode(left.value.slice(last,anchor.offset)));
  const span=node("span");mirror.append(span);spans.push(span);last=anchor.offset;
 }
 mirror.append(document.createTextNode(left.value.slice(last)+"\n"));
 const ltop=mirror.getBoundingClientRect().top+parseFloat(style.paddingTop);
 const rtop=right.getBoundingClientRect().top+right.clientTop+parseFloat(getComputedStyle(right).paddingTop)-right.scrollTop;
 const lmax=Math.max(0,left.scrollHeight-left.clientHeight),rmax=Math.max(0,right.scrollHeight-right.clientHeight);
 const pairs=[[0,0]];
 for(let i=0;i<anchors.length;i++){
  const x=Math.max(0,spans[i].getBoundingClientRect().top-ltop);
  const y=Math.max(0,anchors[i].element.getBoundingClientRect().top-rtop);
  const prev=pairs.at(-1);
  if(x>prev[0]+1&&y>prev[1]+1&&x<lmax&&y<rmax)pairs.push([x,y]);
 }
 if(lmax>0&&rmax>0)pairs.push([lmax,rmax]);
 mapping=pairs;
}
function translate(pos,from,to){
 const a=from===left?0:1,b=1-a;
 if(mapping.length<2)return 0;
 for(let i=1;i<mapping.length;i++){
  const lo=mapping[i-1],hi=mapping[i];
  if(pos<=hi[a])return lo[b]+(hi[b]-lo[b])*Math.max(0,(pos-lo[a])/(hi[a]-lo[a]));
 }
 return mapping.at(-1)[b];
}
function follow(from){
 if(!enabled()||mapping.length<2)return;
 const to=from===left?right:left;
 const y=Math.round(translate(from.scrollTop,from,to));
 if(Math.abs(to.scrollTop-y)<=1)return;
 to.scrollTop=y;expected.set(to,to.scrollTop);
}
function scrolled(from){
 const wanted=expected.get(from);expected.delete(from);
 if(wanted!==undefined&&Math.abs(from.scrollTop-wanted)<=1)return;
 active=from;follow(from);
}
left.addEventListener("scroll",()=>scrolled(left),{passive:true});
right.addEventListener("scroll",()=>scrolled(right),{passive:true});
for(const pane of [left,right])for(const type of ["wheel","pointerdown","touchstart","keydown"])pane.addEventListener(type,()=>{expected.delete(pane);active=pane},{passive:true});
function refreshMapping(){
 cancelAnimationFrame(refreshFrame);
 refreshFrame=requestAnimationFrame(()=>{measure();follow(active)});
}
sync.addEventListener("change",()=>{expected=new WeakMap();active=left;refreshMapping()});
window.addEventListener("resize",refreshMapping);
if(typeof ResizeObserver!=="undefined"){
 const observer=new ResizeObserver(refreshMapping);
 observer.observe(left);observer.observe(right);observer.observe($("preview"));
}
function render(){
 const host=$("preview");host.replaceChildren();anchors=[];
 if(!state)return;
 const body=left.value;
 const parsed=window.HpiiDzenTables?HpiiDzenTables.splitMarkdown(body):{parts:[{kind:"text",text:body}],errors:[]};
 let cursor=0;
 function append(element,offset){host.append(element);anchors.push({element,offset})}
 for(const part of parsed.parts){
  const raw=part.kind==="table"?part.raw:part.text;
  let start=body.indexOf(raw,cursor);if(start<0)start=cursor;
  cursor=start+raw.length;
  if(part.kind==="table"){
   const wrap=node("div");wrap.className="table-wrap";const table=node("table");
   const head=node("thead"),tr=node("tr");
   for(const [i,cell] of part.headers.entries()){const th=node("th");th.style.textAlign=part.align[i];inline(th,cell);tr.append(th)}
   head.append(tr);table.append(head);const tbody=node("tbody");
   for(const row of part.rows){const line=node("tr");for(const [i,cell] of row.entries()){const td=node("td");td.style.textAlign=part.align[i];inline(td,cell);line.append(td)}tbody.append(line)}
   table.append(tbody);wrap.append(table);append(wrap,start);continue;
  }
  const lines=raw.split("\n"),offsets=[];let at=start;
  for(const l of lines){offsets.push(at);at+=l.length+1}
  let para=[],paraStart=0;
  const flush=()=>{if(para.length){const p=node("p");inline(p,para.join(" "));append(p,paraStart);para=[]}};
  for(let i=0;i<lines.length;i++){
   const l=lines[i].trim(),offset=offsets[i];
   if(!l){flush();continue}
   const image=/^!\[([^\]]+)\]\(illustrations\/([a-z0-9-]+)\/([a-z0-9][a-z0-9_-]*\.(?:png|webp|jpg|jpeg))\)$/.exec(l);
   if(image&&image[2]===state.id){flush();const img=node("img");img.src="/assets/editorial/inline/"+state.id+"/"+image[3];img.alt=image[1];img.loading="eager";img.addEventListener("load",refreshMapping);append(img,offset);continue}
   if(/^#{2,3} /.test(l)){flush();const h=node(l.startsWith("### ")?"h3":"h2");inline(h,l.replace(/^#{2,3} /,""));append(h,offset);continue}
   if(/^> /.test(l)){flush();const q=node("blockquote");let content=l.slice(2);while(i+1<lines.length&&/^> /.test(lines[i+1].trim()))content+=" "+lines[++i].trim().slice(2);inline(q,content);append(q,offset);continue}
   if(/^[-*] |^\d+\. /.test(l)){flush();const ordered=/^\d+\. /.test(l),pattern=ordered?/^\d+\. /:/^[-*] /,list=node(ordered?"ol":"ul");let v=l;while(true){const li=node("li");inline(li,v.replace(pattern,""));list.append(li);if(i+1>=lines.length||!pattern.test(lines[i+1].trim()))break;v=lines[++i].trim()}append(list,offset);continue}
   if(!para.length)paraStart=offset;para.push(l);
  }
  flush();
 }
 active=left;refreshMapping();
}
function findRows(){
 const q=$("search").value.trim().toLocaleLowerCase("ru-RU"),host=$("searchResults");host.replaceChildren();
 const matching=rows.filter(r=>validId(r.id)&&(!q||(r.title+" "+r.id).toLocaleLowerCase("ru-RU").includes(q)));
 for(const r of matching.slice(0,40)){const item=node("div");item.className="item";const a=node("a",r.title);a.href="/admin/article-edit/?id="+encodeURIComponent(r.id);item.append(a,node("small",r.published||""));host.append(item)}
 if(!matching.length)host.append(node("p","Материалы не найдены."));
}
async function load(){
 if(busy)return;busy=true;controls();status("Читаю текущую редакцию…");const v=++version;
 try{
  if(!validId(id)){
   const list=await window.HpiiAdminAuth.fetchApi("/api/dossier");
   if(v!==version)return;rows=list.published.slice().sort((a,b)=>String(b.published_at_utc||b.published).localeCompare(String(a.published_at_utc||a.published)));
   $("picker").hidden=false;findRows();status("Выбери статью. Редактируются материалы, опубликованные из редакционной очереди ХПИИ.");return;
  }
  const result=await window.HpiiAdminAuth.fetchApi("/api/article-edit?article_id="+encodeURIComponent(id));
  if(v!==version)return;state=result;dirty=false;
  $("editor").hidden=false;$("title").textContent=result.title;
  $("cover").src="/"+result.cover;$("body").value=result.pending?result.pending_markdown:result.markdown;
  $("publicLink").href="/articles/"+id+"/";$("dzenWarning").hidden=!result.dzen_published;
  left.scrollTop=0;right.scrollTop=0;expected=new WeakMap();render();
  if(result.pending)status("Правка принята и ожидает проверки. Нажми «Проверить статус» после обработки.");
  else if(result.result?.status==="rejected")status("Последняя правка отклонена: "+result.result.error+". Опубликованный текст не изменён.",true);
  else if(result.result?.status==="applied")status("Правка сохранена в источнике сайта и RSS. Публичная страница и текст для Дзена обновляются отдельными сборками.");
  else status("Можно редактировать.");
 }catch(e){status("Не удалось открыть: "+e.message,true)}
 finally{busy=false;controls()}
}
function insert(value,start,end){
 const t=$("body");t.setRangeText(value,start,end,"end");t.focus();setDirty();render();
}
$("body").addEventListener("input",()=>{setDirty();render()});
for(const b of document.querySelectorAll("[data-wrap]"))b.addEventListener("click",()=>{const t=$("body"),a=t.selectionStart,z=t.selectionEnd,m=b.dataset.wrap;if(a===z)return;const s=t.value.slice(a,z);insert(s.startsWith(m)&&s.endsWith(m)?s.slice(m.length,-m.length):m+s+m,a,z)});
$("paragraph").addEventListener("click",()=>{const t=$("body");insert("\n\n",t.selectionStart,t.selectionStart)});
$("heading").addEventListener("click",()=>{const t=$("body"),a=t.value.lastIndexOf("\n",Math.max(0,t.selectionStart-1))+1;insert("## ",a,a)});
$("restore").addEventListener("click",()=>{if(state&&confirm("Вернуть первоначальный текст в редактор? Публичная статья изменится только после сохранения.")){$("body").value=state.original;setDirty();render()}});
$("reload").addEventListener("click",()=>{if(!dirty||confirm("Отменить несохранённые изменения и прочитать текущую редакцию?"))void load()});
$("search").addEventListener("input",findRows);
$("save").addEventListener("click",async()=>{
 if(!state||busy||state.pending||!dirty)return;
 if(!confirm("Сохранить изменения на сайте и в источнике для Дзена?"))return;
 busy=true;controls();status("Отправляю исправление на проверку…");
 try{
  const r=await window.HpiiAdminAuth.fetchApi("/api/article-edit",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({article_id:state.id,base_sha:state.base_sha,article_markdown:$("body").value})});
  if(r.status==="queued"){state.pending=true;dirty=false;status("Правка принята. Сайт ещё не изменён. Нажми «Проверить статус» после обработки.")}
  else if(r.status==="unchanged"){dirty=false;status("Текст уже совпадает с сохранённым.")}
 }catch(e){status("Сохранение не подтверждено: "+e.message+". Твой текст остался в редакторе.",true)}
 finally{busy=false;controls()}
});
window.addEventListener("beforeunload",e=>{if(dirty){e.preventDefault();e.returnValue=""}});
window.addEventListener("hpii-admin-authorized",load);
window.addEventListener("hpii-admin-signout",()=>{version++;state=null;dirty=false;$("body").value="";$("editor").hidden=true;$("picker").hidden=true;controls()});
if(document.documentElement.classList.contains("hpii-authorized"))void load();
})();