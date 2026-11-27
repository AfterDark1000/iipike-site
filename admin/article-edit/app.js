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
function render(){
 const host=$("preview");host.replaceChildren();
 if(!state)return;
 const body=$("body").value;
 const parsed=window.HpiiDzenTables?HpiiDzenTables.splitMarkdown(body):{parts:[{kind:"text",text:body}],errors:[]};
 for(const part of parsed.parts){
  if(part.kind==="table"){
   const wrap=node("div");wrap.className="table-wrap";const table=node("table");
   const head=node("thead"),tr=node("tr");
   for(const cell of part.headers){const th=node("th");inline(th,cell);tr.append(th)}
   head.append(tr);table.append(head);const tbody=node("tbody");
   for(const row of part.rows){const line=node("tr");for(const cell of row){const td=node("td");inline(td,cell);line.append(td)}tbody.append(line)}
   table.append(tbody);wrap.append(table);host.append(wrap);continue;
  }
  for(const group of part.text.split(/\n\s*\n/)){
   if(!group.trim())continue;
   const lines=group.split("\n").filter(x=>x.trim());
   let para=[];
   const flush=()=>{if(para.length){const p=node("p");inline(p,para.join(" "));host.append(p);para=[]}};
   for(let i=0;i<lines.length;i++){
    const l=lines[i],image=/^!\[([^\]]+)\]\(illustrations\/([a-z0-9-]+)\/([a-z0-9][a-z0-9_-]*\.(?:png|webp|jpg|jpeg))\)$/.exec(l);
    if(image&&image[2]===state.id){flush();const img=node("img");img.src="/assets/editorial/inline/"+state.id+"/"+image[3];img.alt=image[1];img.loading="lazy";host.append(img);continue}
    if(/^#{2,3} /.test(l)){flush();const h=node(l.startsWith("### ")?"h3":"h2");inline(h,l.replace(/^#{2,3} /,""));host.append(h);continue}
    if(/^> /.test(l)){flush();const q=node("blockquote");let content=l.slice(2);while(i+1<lines.length&&/^> /.test(lines[i+1]))content+=" "+lines[++i].slice(2);inline(q,content);host.append(q);continue}
    if(/^[-*] |^\d+\. /.test(l)){flush();const ordered=/^\d+\. /.test(l),pattern=ordered?/^\d+\. /:/^[-*] /,list=node(ordered?"ol":"ul");let v=l;while(true){const li=node("li");inline(li,v.replace(pattern,""));list.append(li);if(i+1>=lines.length||!pattern.test(lines[i+1]))break;v=lines[++i]}host.append(list);continue}
    para.push(l);
   }
   flush();
  }
 }
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
  render();
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