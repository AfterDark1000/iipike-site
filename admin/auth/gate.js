// UX gate for static GitHub Pages. Security boundary is the Worker API, not these public files.
import {HpiiAdminAuth} from "/admin/auth/hpii-auth-client.js";

const auth = new HpiiAdminAuth("https://hpii-admin-gateway.svuktablet.workers.dev");
window.HpiiAdminAuth = auth;
const holder=document.createElement("section");
holder.id="hpii-login-gate";
holder.setAttribute("role","region");
holder.setAttribute("aria-label","Вход в админку");
holder.innerHTML='<div class="hpii-login-card"><h1>Админка ХПИИ</h1><p>Вход через GitHub. Доступ к управлению — только для владельца проекта.</p><p id="hpii-login-message" role="status" aria-live="polite">Проверяю сессию…</p><button id="hpii-login-button" type="button" disabled>Войти через GitHub</button><p class="hpii-login-help">Один вход для всех разделов и вкладок этого браузера на 7 дней. Нажми «Выйти из админки» на любом разделе, если компьютер общий. Исходники сайта публичны; действия проверяет защищённый сервер.</p></div>';
document.body.append(holder);
const button=document.getElementById("hpii-login-button");
const notice=document.getElementById("hpii-login-message");
const signout=document.createElement("button");
signout.id="hpii-signout";
signout.type="button";
signout.textContent="Выйти из админки";
signout.title="Завершить общий вход на этом браузере";
signout.hidden=true;
signout.style.cssText="position:fixed;right:14px;bottom:14px;z-index:1000;border:1px solid #b6c7c3;border-radius:9px;background:#fffefb;color:#235650;padding:8px 12px;font:600 12px system-ui,sans-serif;cursor:pointer;box-shadow:0 3px 12px #132c2522";
document.body.append(signout);
let checkVersion=0;
function show(message){notice.textContent=message}
function showLogin(message){
  document.documentElement.classList.remove("hpii-authorized");
  holder.hidden=false;
  signout.hidden=true;
  show(message);
  button.disabled=false;
}
function showAuthorized(login){
  holder.hidden=true;
  signout.hidden=false;
  document.documentElement.classList.add("hpii-authorized");
  window.dispatchEvent(new CustomEvent("hpii-admin-authorized",{detail:{login}}));
}
async function check(){
  const version=++checkVersion;
  if (!auth.getToken()){showLogin("Сессии нет. Войди через GitHub.");return}
  try{
    const result=await auth.session();
    if(version!==checkVersion)return;
    if(result.login!=="AfterDark1000")throw Error("Аккаунт не разрешён");
    showAuthorized(result.login);
  }catch(e){
    if(version!==checkVersion)return;
    // A transient network failure never destroys the stored session.
    // Only an actual Worker 401 removes it, in HpiiAdminAuth.fetchApi.
    showLogin("Не удалось подтвердить сессию: "+e.message);
  }
}
button.addEventListener("click", async()=>{
  button.disabled=true;
  show("Откроется окно GitHub. Подтверди вход и вернись сюда.");
  try{
    await auth.login();
    await check();
  }catch(e){showLogin("Ошибка входа: "+e.message)}
});
signout.addEventListener("click",()=>{
  window.dispatchEvent(new CustomEvent("hpii-admin-signout"));
});
window.addEventListener("hpii-admin-signout",()=>{
  ++checkVersion;
  auth.logout();
  showLogin("Вы вышли из админки на этом браузере.");
});
// localStorage synchronizes a single confirmed sign-in (and sign-out) across
// all same-origin tabs, without another GitHub OAuth popup.
window.addEventListener("storage",event=>{
  if(event.key!==auth.storageKey && event.key!==null)return;
  if(!auth.getToken()){
    ++checkVersion;
    showLogin("Сессия завершена в другой вкладке.");
  }else{
    void check();
  }
});
void check();
