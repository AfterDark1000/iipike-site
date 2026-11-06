// Offline DOM behavior tests for HPII analytics consent.
// No browser, network, external packages, or publishing.
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const source = fs.readFileSync(path.join(__dirname, "../assets/social-footer.js"), "utf8");
const KEY = "hpii.analytics.v1";

class Node {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.className = "";
    this.attributes = {}; this.events = {}; this.parent = null; this.textContent = "";
  }
  append(...items) { items.forEach(x => this.appendChild(x)); }
  appendChild(x) { this.children.push(x); x.parent = this; return x; }
  setAttribute(k, v) { this.attributes[k] = v; }
  addEventListener(type, fn) { this.events[type] = fn; }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter(x => x !== this);
    this.parent = null;
  }
  querySelector(selector) {
    if (selector[0] === "." && this.className.split(/\s+/).includes(selector.slice(1))) return this;
    for (const c of this.children) {
      const found = c.querySelector(selector);
      if (found) return found;
    }
    return null;
  }
  click() {
    if (!this.events.click) throw Error("No click handler for " + this.className);
    this.events.click();
  }
  focus() { this.focused = true; }
}
function run(saved = new Map()) {
  let requests = 0, reloads = 0;
  const scripts = [];
  const body = new Node("body");
  const document = {
    body, scripts, referrer: "https://dzen.ru/",
    querySelectorAll: () => [],
    createElement: tag => new Node(tag),
    getElementsByTagName(tag) {
      if (tag === "script") return [{
        parentNode: {
          insertBefore(n) { scripts.push(n); requests++; }
        }
      }];
      return [];
    }
  };
  const window = {
    localStorage: {
      getItem: k => saved.get(k) ?? null,
      setItem: (k, value) => saved.set(k, value)
    },
    location: {reload() { reloads++; }},
  };
  vm.runInNewContext(source, { window, document, location: {href:"https://iipike.ru/articles/example/"} }, { timeout: 400 });
  return {
    window, body, saved,
    requests: () => requests,
    reloads: () => reloads,
    panel: () => body.querySelector(".hpi-consent-panel"),
    button: cls => body.querySelector("." + cls)
  };
}

const first = run();
assert.equal(first.requests(), 0, "No tag before opt-in");
assert.ok(first.panel(), "Unanswered choice shows notice");
assert.equal(first.window.ym, undefined, "No Yandex global before consent");
first.button("hpi-consent-reject").click();
assert.equal(first.saved.get(KEY), "no");
assert.equal(first.requests(), 0);
assert.equal(first.panel(), null, "Notice dismisses after refusal");

const refused = run(first.saved);
assert.equal(refused.requests(), 0, "Refusal persists across pages");
assert.equal(refused.panel(), null, "No repeated notice after refusal");
refused.window.HPIIAnalyticsConsent.open();
assert.ok(refused.panel(), "Settings can always be reopened");
refused.button("hpi-consent-accept").click();
assert.equal(refused.saved.get(KEY), "yes");
assert.equal(refused.requests(), 1, "Consent loads tag exactly once");
assert.equal(refused.panel(), null);
assert.equal(typeof refused.window.ym, "function", "Yandex initialized after permission");
assert.equal(refused.window.ym.a[0][0], 114100188);

refused.window.HPIIAnalyticsConsent.open();
refused.window.HPIIAnalyticsConsent.open();
assert.equal(refused.body.children.filter(x => x.className === "hpi-consent-panel").length, 1);
refused.button("hpi-consent-reject").click();
assert.equal(refused.saved.get(KEY), "no");
assert.equal(refused.reloads(), 1, "Revocation refreshes page and stops further tracking");
assert.equal(run(refused.saved).requests(), 0, "After revocation no analytics loads");

const accepted = run(new Map([[KEY, "yes"]]));
assert.equal(accepted.requests(), 1, "Returning consenting visitor gets tag");
assert.equal(accepted.panel(), null);
console.log("PASS: no consent/no tag, refusal, opt-in, persistence, reopen, revocation");
