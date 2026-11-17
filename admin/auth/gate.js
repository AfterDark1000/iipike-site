// UX gate for static GitHub Pages. Security boundary is the Worker API, not these public files.
import {HpiiAdminAuth} from "/admin/auth/hpii-auth-client.js";

const auth = new HpiiAdminAuth("https://hpii-admin-gateway.svuktablet.workers.dev");
window.HpiiAdminAuth = auth;
const holder=document.createElement("section");
holder.id="hpii-login-gate";
holder.setAttribute("role","region");
holder.setAttribute("aria-label","Вход в админку");
holder.innerHTML='<div class="hpii-login-card"><h1>Админка ХПИИ</h1><p>Вход через GitHub. Доступ к управлению — только для владельца проекта.</p><p id="hpii-login-message" role="status" aria-live="polite">Проверяю сессию…</p><button id="hpii-login-button" type="button" disabled>Войти через GitHub</button><p class="hpii-login-help">Публичные исходники сайта и репозитория этот вход не скрывает. Решения сохраняются только через защищённый сервер.</p></div>';
document.body.append(holder);
const button=document.getElementById("hpii-login-button");
const notice=document.getElementById("hpii-login-message");
const label=()=>document.title;
function show(message){notice.textContent=message}
function showLogin(message){
  document.documentElement.classList.remove("hpii-authorized");
  holder.hidden=false;show(message);
  button.disabled=false;
}
function showAuthorized(login){
  holder.hidden=true;
  document.documentElement.classList.add("hpii-authorized");
  window.dispatchEvent(new CustomEvent("hpii-admin-authorized",{detail:{login}}));
}
async function check(){
  if (!auth.getToken()){showLogin("Сессии нет. Войди через GitHub.");return}
  try{
    const result=await auth.session();
    if(result.login!=="AfterDark1000")throw Error("Аккаунт не разрешён");
    showAuthorized(result.login);
  }catch(e){
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
window.addEventListener("hpii-admin-signout",()=>{
  auth.logout();
  showLogin("Вы вышли из админки.");
});
check();
