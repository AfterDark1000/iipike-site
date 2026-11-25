const $=id=>document.getElementById(id);
let state=null,busy=false;
function el(tag,txt){const node=document.createElement(tag);if(txt!==undefined)node.textContent=txt;return node}
function notice(msg,error=false){$("status").textContent=msg;$("status").classList.toggle("error",error)}
function render(){
  $("refresh").disabled=busy;$("search").disabled=busy||!state;
  $("members").replaceChildren();$("results").replaceChildren();
  if(!state){$("count").textContent="";return}
  const byId=new Map(state.published.map(r=>[r.id,r])),members=new Set(state.config.items);
  $("count").textContent="("+members.size+")";
  function row(r,action){
    const item=el("div"),copy=el("div"),a=el("a",r.title),small=el("small",r.published+" · "+r.id);
    item.className="item";a.href="/articles/"+r.id+"/";a.target="_blank";a.rel="noopener";
    copy.append(a,small);
    const button=el("button",action==="add"?"В Досье":"Исключить");
    button.type="button";button.disabled=busy;button.addEventListener("click",()=>change(r,action));
    item.append(copy,button);return item;
  }
  for(const id of state.config.items){const r=byId.get(id);if(r)$("members").append(row(r,"remove"))}
  if(!members.size)$("members").append(el("p","Пока нет материалов."));
  const q=$("search").value.trim().toLocaleLowerCase("ru-RU");
  const matches=state.published.filter(r=>!members.has(r.id)&&(!q||(r.title+" "+r.id).toLocaleLowerCase("ru-RU").includes(q)))
    .sort((a,b)=>String(b.published_at_utc||b.published).localeCompare(String(a.published_at_utc||a.published)));
  for(const r of matches.slice(0,25))$("results").append(row(r,"add"));
  $("hint").textContent=matches.length?"Показано "+Math.min(25,matches.length)+" из "+matches.length+". Уточни поиск.":"Нет подходящих публикаций.";
}
async function load(){
  if(busy)return;busy=true;render();notice("Читаю актуальный список…");
  try{state=await window.HpiiAdminAuth.fetchApi("/api/dossier");notice("Список прочитан из GitHub.")}
  catch(e){state=null;notice("Не удалось прочитать список: "+e.message,true)}
  finally{busy=false;render()}
}
async function change(r,action){
  if(busy||!state)return;
  if(action==="remove"&&!confirm("Исключить из Досье? Сама статья останется на сайте."))return;
  busy=true;render();
  try{
    const result=await window.HpiiAdminAuth.fetchApi("/api/dossier",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({article_id:r.id,action,config_sha:state.config_sha})});
    state.config.items=result.items;state.config_sha=result.config_sha;
    notice(result.status==="unchanged"?"Список уже соответствует запросу.":"Сохранено в GitHub. Публичные страницы обновятся после пересборки сайта.");
  }catch(e){notice("Изменение не подтверждено: "+e.message+". Обнови список перед повтором.",true);state=null}
  finally{busy=false;render()}
}
$("search").addEventListener("input",render);$("refresh").addEventListener("click",load);
window.addEventListener("hpii-admin-authorized",load);
window.addEventListener("hpii-admin-signout",()=>{state=null;render()});
if(document.documentElement.classList.contains("hpii-authorized"))void load();
