import assert from "node:assert/strict";
import {createSign,generateKeyPairSync,webcrypto} from "node:crypto";
import test from "node:test";
import gateway, {FirstCarText} from "../src/index.mjs";

globalThis.crypto ||= webcrypto;
const repository = "AfterDark1000/iipike-site";
const issuer = "https://token.actions.githubusercontent.com";
const ref = "refs/heads/main";
const url = "https://dzen.ru/a/avwsiGM1tFu-0T5x";
const text = "Private owner text";
const path = "/api/first-car/workflow-text";
const env = {
  ADMIN_ORIGIN:"https://iipike.ru",
  BACKEND_ORIGIN:"https://hpii-test.workers.dev",
  GITHUB_CLIENT_ID:"client",GITHUB_CLIENT_SECRET:"dummy",
  SESSION_SIGNING_KEY:"test-hmac-key-for-first-car-at-least-32",
  GITHUB_REPO_TOKEN:"dummy",ALLOWED_GITHUB_USER_ID:"284211090",
  FIRST_CAR_OWNER_TEXT_ARTICLE_ID:url.split("/").at(-1),
  FIRST_CAR_TEXT:{idFromName: name => name, get: () => ({fetch:async target => {
    assert.equal(target,"https://first-car.internal/texts");
    return Response.json({[url]:text,"https://dzen.ru/a/offline-other-doc":"Inaccessible text"});
  }})}
};

test("only a signed short-lived GitHub identity for the existing main workflow may read private text", async t => {
  const {privateKey,publicKey}=generateKeyPairSync("rsa",{modulusLength:2048});
  const key={...publicKey.export({format:"jwk"}),kid:"fixture"};
  const now=Math.floor(Date.now()/1000);
  const claims={iss:issuer,aud:"hpii-first-car-text",exp:now+300,nbf:now-1,ref,
    repository,repository_id:"1425286669",workflow_ref:`${repository}/.github/workflows/commenting-queue.yml@${ref}`,
    event_name:"workflow_run",runner_environment:"github-hosted"};
  const encode=data => Buffer.from(JSON.stringify(data)).toString("base64url");
  const token=(values={},header={alg:"RS256",kid:"fixture"})=>{
    const signed=encode(header)+"."+encode({...claims,...values});
    return signed+"."+createSign("RSA-SHA256").update(signed).sign(privateKey,"base64url");
  };
  const access=(identity,route=path,overrides={})=>gateway.fetch(new Request(env.BACKEND_ORIGIN+route,{
    headers:identity ? {authorization:"Bearer "+identity} : {}
  }),{...env,...overrides});
  let status=200;
  const keys=t.mock.method(globalThis,"fetch",async(input,options)=>{
    assert.equal(input,issuer+"/.well-known/jwks");
    assert.equal(options.redirect,"manual");
    assert.equal(options.headers,undefined);
    return Response.json({keys:[key]},{status});
  });
  for (const identity of [
    null, "owner-session.signature", token({aud:"other"}), token({iss:"https://other.example"}),
    token({repository_id:"1"}), token({ref:"refs/pull/1/merge"}), token({event_name:"pull_request"}),
    token({workflow_ref:`${repository}/.github/workflows/other.yml@${ref}`}),
    token({runner_environment:"self-hosted"}), token({exp:now-1}), token({nbf:now+30}), token({exp:now+900}),
    token({}, {alg:"none",kid:"fixture"}),
  ]) {
    const refused=await access(identity);
    assert.equal(refused.status,401);
    assert.deepEqual(await refused.json(),{ok:false,error:"workflow_identity_required"});
  }
  assert.equal(keys.mock.callCount(),0);
  assert.equal((await access(token(),path+"?url=other")).status,400);
  const valid=token();
  assert.equal((await access(valid.replace(/\.[^.]+$/,".ZmFrZQ"))).status,401);
  status=302;
  assert.equal((await access(valid)).status,401);
  status=200;
  const response=await access(valid);
  assert.equal(response.headers.get("cache-control"),"no-store");
  assert.equal(response.headers.get("access-control-allow-origin"),null);
  assert.deepEqual(await response.json(),{ok:true,texts:{[url]:text}});
  const disabled=await access(valid,path,{FIRST_CAR_OWNER_TEXT_ARTICLE_ID:undefined});
  assert.deepEqual(await disabled.json(),{ok:true,texts:{}});
  assert.equal((await access(valid,path,{FIRST_CAR_TEXT:undefined})).status,503);
  const outage=await access(valid,path,{FIRST_CAR_TEXT:{idFromName: name=>name,
    get:()=>({fetch:()=>{throw Error("Sensitive fake service error")}})}});
  assert.equal(outage.status,502);
  assert.deepEqual(await outage.json(),{ok:false,error:"first_car_text_unavailable"});
});

test("submitted private text is idempotent and an expiration alarm deletes it", async t => {
  const now=Date.now();
  const clock=t.mock.method(Date,"now",()=>now);
  const entries=new Map();
  let scheduled=null;
  const storage={
    list:async()=>new Map(entries),get:async key=>entries.get(key),put:async(key,value)=>entries.set(key,value),
    delete:async keys=>keys.forEach(key=>entries.delete(key)),
    getAlarm:async()=>scheduled,setAlarm:async when=>{scheduled=when;},
    transaction:callback=>callback(storage),
  };
  const durable=new FirstCarText({storage});
  const read=action=>durable.fetch(new Request("https://first-car.internal/"+action)).then(response=>response.json());
  const submit=(value,expires)=>durable.fetch(new Request("https://first-car.internal/submit",{
    method:"POST",body:JSON.stringify({url,text:value,expires}),
  })).then(response=>response.json());
  assert.deepEqual(await submit(text,now+500),{accepted:true});
  assert.deepEqual(await submit(text,now+700),{accepted:true});
  assert.deepEqual(await submit("different text",now+700),{accepted:false,reason:"text_already_submitted"});
  assert.equal(scheduled,now+500);
  assert.deepEqual(await read("pending"),[url]);
  assert.deepEqual(await read("texts"),{[url]:text});
  clock.mock.mockImplementation(()=>now+500);
  assert.deepEqual(await read("texts"),{});
  await durable.alarm();
  assert.equal(entries.size,0);
  assert.deepEqual(await submit(text,now+500),{accepted:false,reason:"article_expired"});
});
