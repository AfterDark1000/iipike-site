import test from "node:test";
import assert from "node:assert/strict";
import {HpiiAdminAuth} from "../../admin/auth/hpii-auth-client.js";

const BACKEND="https://hpii-admin-gateway.example.workers.dev";
function storage(initial={}) {
  const values=new Map(Object.entries(initial));
  return {
    getItem: key => values.get(key)??null,
    setItem: (key,value) => {values.set(key,String(value));},
    removeItem: key => {values.delete(key);}
  };
}
function browser(t,{local=storage(),tab=storage()}={}) {
  const saved=globalThis.window,oldFetch=globalThis.fetch;
  globalThis.window={localStorage:local,sessionStorage:tab};
  t.after(()=>{globalThis.window=saved;globalThis.fetch=oldFetch;});
  return {local,tab};
}
const token="eyJraW5kIjoic2Vzc2lvbiJ9.signaturE";

test("one signed-in admin session survives navigation and different tabs",t=>{
  const {local,tab}=browser(t);
  const first=new HpiiAdminAuth(BACKEND);
  first._saveToken(token);
  assert.equal(local.getItem("hpii-admin-session-v2"),token);
  assert.equal(tab.getItem("hpii-admin-session-v2"),null);
  const second=new HpiiAdminAuth(BACKEND);
  assert.equal(second.getToken(),token);
  second.logout();
  assert.equal(first.getToken(),null);
  assert.equal(local.getItem("hpii-admin-session-v2"),null);
});
test("migrates still-valid legacy tab token into shared storage without OAuth popup",t=>{
  const legacy=storage({"hpii-admin-session-v1":token});
  const {local,tab}=browser(t,{tab:legacy});
  const auth=new HpiiAdminAuth(BACKEND);
  assert.equal(auth.getToken(),token);
  assert.equal(local.getItem("hpii-admin-session-v2"),token);
  assert.equal(tab.getItem("hpii-admin-session-v1"),null);
});
test("rejects malformed stored tokens, without sending them to Worker",t=>{
  const {local}=browser(t,{local:storage({"hpii-admin-session-v2":"javascript:malicious"})});
  const auth=new HpiiAdminAuth(BACKEND);
  assert.equal(auth.getToken(),null);
  assert.equal(local.getItem("hpii-admin-session-v2"),null);
});
test("private browsing can use tab storage when persistent storage is forbidden",t=>{
  const local={getItem(){throw Error("no storage")},setItem(){throw Error("no storage")},
    removeItem(){throw Error("no storage")}};
  browser(t,{local});
  const auth=new HpiiAdminAuth(BACKEND);
  auth._saveToken(token);
  assert.equal(auth.getToken(),token);
  auth.logout();
  assert.equal(auth.getToken(),null);
});
test("auth outage preserves stored session; real 401 clears it across tabs",async t=>{
  const {local}=browser(t);
  const auth=new HpiiAdminAuth(BACKEND);
  auth._saveToken(token);
  globalThis.fetch=async()=>Response.json({ok:false,error:"worker_unavailable"},{status:503});
  await assert.rejects(auth.session(),/worker_unavailable/);
  assert.equal(local.getItem("hpii-admin-session-v2"),token);
  globalThis.fetch=async()=>Response.json({ok:false,error:"login_required"},{status:401});
  await assert.rejects(auth.session(),/login_required/);
  assert.equal(local.getItem("hpii-admin-session-v2"),null);
});
