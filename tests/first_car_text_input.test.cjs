"use strict";
const assert = require("node:assert/strict");
const {test} = require("node:test");
const {readSubmittedText} = require("../scripts/first_car_text_input.cjs");

const env = {
  ACTIONS_ID_TOKEN_REQUEST_URL: "https://pipelines.actions.githubusercontent.com/oidc?api-version=2.0",
  ACTIONS_ID_TOKEN_REQUEST_TOKEN: "fixture-request-only",
};
const url = "https://dzen.ru/a/first-car-fixture";
const text = "Private submitted article text. ".repeat(16);
const jwt = "fixture.header.signature";

test("scoped OIDC and private Worker requests use one deadline and no redirects", async () => {
  for (const texts of [{}, {[url]: text}]) {
    const signal = new AbortController().signal;
    const calls = [];
    const received = await readSubmittedText({env, signal, fetcher: async (target, opts) => {
      assert.equal(opts.redirect, "error");
      assert.equal(opts.signal, signal);
      const uri = new URL(target);
      calls.push(uri.hostname);
      if (calls.length === 1) {
        assert.equal(uri.searchParams.get("audience"), "hpii-first-car-text");
        assert.equal(opts.headers.authorization, "Bearer " + env.ACTIONS_ID_TOKEN_REQUEST_TOKEN);
        return Response.json({value: jwt});
      }
      assert.equal(opts.headers.authorization, "Bearer " + jwt);
      assert.equal(uri.pathname, "/api/first-car/workflow-text");
      return Response.json({ok:true,texts});
    }});
    assert.deepEqual(calls, ["pipelines.actions.githubusercontent.com","hpii-admin-gateway.svuktablet.workers.dev"]);
    assert.deepEqual(received,texts);
  }
});

test("issuer or storage failures and unexpected input never report response secrets", async () => {
  for (const [statuses, expected] of [
    [[401], /GitHub OIDC unavailable/],
    [[200,401], /First Car text unavailable/],
    [[200,503], /First Car text unavailable/],
    [[200,200], /Invalid text input/],
  ]) {
    const fetcher = async () => {
      const status = statuses.shift();
      return Response.json({value:jwt,message:text,ok:true,texts:{[url]:"title only"}},{status});
    };
    await assert.rejects(readSubmittedText({env,fetcher}), expected);
    assert.deepEqual(statuses,[]);
  }
  await assert.rejects(readSubmittedText({env:{...env,ACTIONS_ID_TOKEN_REQUEST_URL:"https://actions.githubusercontent.com.attacker.test/"},
    fetcher:() => assert.fail("Unexpected outbound request")}), /Missing GitHub OIDC identity/);
});

test("both stalled network requests can be aborted by the shared deadline", async () => {
  for (const stallAt of [1,2]) {
    let calls = 0;
    const controller = new AbortController();
    const reading = readSubmittedText({env,signal:controller.signal,fetcher:async (_url,{signal}) => {
      if (++calls !== stallAt) return Response.json({value:jwt});
      return new Promise((_,reject) => {
        signal.addEventListener("abort", () => reject(signal.reason), {once:true});
        queueMicrotask(() => controller.abort(new DOMException("Deadline", "TimeoutError")));
      });
    }});
    await assert.rejects(reading, {name:"TimeoutError"});
    assert.equal(calls,stallAt);
  }
});
