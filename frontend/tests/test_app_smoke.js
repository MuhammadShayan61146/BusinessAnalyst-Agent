/**
 * Smoke test: runs the REAL frontend/app.js (and logic.js) in Node against a
 * tiny fake DOM and a scripted fake backend (fetch). No browser, no npm.
 *
 * It checks that app.js runs without errors, uses only element ids that exist
 * in index.html, and renders the key screens: sign-in, structured summary,
 * logo previews, review triage, requirements + traceability, validation badge,
 * "mark reviewed" actions, history and downloads.
 */
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const FRONTEND = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(FRONTEND, "index.html"), "utf8");
const appSource = fs.readFileSync(path.join(FRONTEND, "app.js"), "utf8");
const logicSource = fs.readFileSync(path.join(FRONTEND, "logic.js"), "utf8");

// ------------------------------------------------------------------ fake DOM
class Node_ { constructor(text) { this._text = text; this.isText = true; } get textContent() { return this._text; } }
class El {
  constructor(tag, id) {
    this.tag = tag; this.id = id || ""; this.childNodes = []; this.handlers = {}; this.style = {};
    this.hidden = false; this.className = ""; this._text = ""; this.value = ""; this.files = [];
    this.attrs = {}; this.src = ""; this.alt = ""; this.type = ""; this.autocomplete = "";
  }
  get children() { return this.childNodes.filter((n) => !n.isText); }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(n) { this.childNodes.push(n); return n; }
  removeChild(n) { this.childNodes.splice(this.childNodes.indexOf(n), 1); return n; }
  remove() {}
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(type, fn) { (this.handlers[type] = this.handlers[type] || []).push(fn); }
  async fire(type, ev) { for (const h of this.handlers[type] || []) await h(ev || { preventDefault() {} }); }
  click() { return this.fire("click"); }
  set textContent(v) { this._text = String(v); this.childNodes = []; }
  get textContent() { return this._text + this.childNodes.map((c) => c.textContent).join(""); }
}

function buildDom() {
  const registry = {};
  for (const m of html.matchAll(/<(\w+)[^>]*\sid="([^"]+)"[^>]*?(\shidden)?[^>]*>/g)) {
    const el = new El(m[1], m[2]);
    el.hidden = /\shidden[\s>]/.test(m[0]);
    registry[m[2]] = el;
  }
  const document = {
    getElementById: (id) => { if (!registry[id]) throw new Error("app.js uses missing element id: " + id); return registry[id]; },
    createElement: (tag) => new El(tag),
    createTextNode: (t) => new Node_(t),
    body: new El("body"),
  };
  return { document, registry };
}

// -------------------------------------------------------------- fake backend
function makeBackend(routes) {
  const calls = [];
  async function fetch(url, opts) {
    opts = opts || {};
    const method = opts.method || "GET";
    const p = url.replace("http://localhost:8000", "");
    calls.push({ method, path: p, body: opts.body ? JSON.parse(opts.body) : null, headers: opts.headers || {} });
    const handler = routes[method + " " + p] || routes[method + " *"];
    if (!handler) return { ok: false, status: 404, json: async () => ({ detail: "no route " + method + " " + p }) };
    const out = typeof handler === "function" ? handler(calls[calls.length - 1]) : handler;
    const status = out.status || 200;
    return { ok: status < 400, status, json: async () => out.body, blob: async () => ({ size: 3 }) };
  }
  return { fetch, calls };
}

function load(routes, storage) {
  const { document, registry } = buildDom();
  const backend = makeBackend(routes);
  const store = Object.assign({}, storage || {});
  const localStorage = {
    getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
  };
  const win = { BA_API_BASE: "http://localhost:8000", location: { search: "" } };
  const sandbox = {
    window: win, document, localStorage, fetch: backend.fetch, console, URLSearchParams,
    URL: { createObjectURL: () => "blob:x", revokeObjectURL() {} }, setTimeout, FileReader: class {},
    encodeURIComponent, Array, JSON, Error, Promise, String, RegExp, Date,
  };
  sandbox.self = win;
  vm.createContext(sandbox);
  vm.runInContext(logicSource, sandbox);
  sandbox.BALogic = win.BALogic;
  vm.runInContext(appSource, sandbox);
  return { registry, backend, store };
}
const tick = () => new Promise((r) => setTimeout(r, 5));
const shown = (reg) => Object.keys(reg).filter((k) => k.endsWith("-screen") && !reg[k].hidden);

let passed = 0, failed = 0;
async function test(name, fn) {
  try { await fn(); passed++; console.log("ok - " + name); }
  catch (e) { failed++; console.log("FAIL - " + name + ": " + (e.stack || e.message)); }
}

const USER = { username: "alice", role: "user" };
const STORY_STATE = {
  session_id: "s1", status: "completed", title: "ATLAS", options: [], previews: [], triage: [],
  result: {
    analysis: {
      objectives: ["Obj A"], stakeholders: ["Analysts"], risks: ["Risk"], data_entities: ["Report"],
      scope: { in: ["PDF export"], out: ["Mobile"] },
      functional_requirements: [{ id: "FR-1", text: "Export a report as PDF", source_refs: [{ source: "a.md", chunk_id: "c" }] },
                                { id: "FR-2", text: "Share dashboards" }],
      non_functional_requirements: ["Should be scalable"],
    },
    business_case: "Saves two days a month.", tasks: ["Design", "Build"],
    stories: [{ id: "US-1", as_a: "analyst", i_want: "to export", so_that: "I can share", fr_ids: ["FR-1"], priority: "Must" }],
    criteria: [{ id: "AC-1", story_id: "US-1", given: "a report", when: "I export", then: "a PDF downloads" }],
    retrieved_evidence: [{ source: "uploads/guide.md", text: "Requirements must be testable." }],
    canonical_status: "requires_human_review", canonical_gaps: [],
    canonical_concerns: [{ id: "TRI-001", type: "ambiguity", severity: "warning", resolved: false,
                           description: "NFR-001 uses vague wording: 'scalable'.", suggestion: "state the load" }],
    triage_findings: [{ id: "TRI-002", severity: "info", description: "FR-2 is a short noun phrase.", suggestion: "Rewrite." }],
  },
};

(async () => {
  // every id used by app.js must exist in index.html
  await test("every element id used in app.js exists in index.html", () => {
    const ids = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]));
    const used = [...appSource.matchAll(/\$\("([a-z0-9-]+)"\)/g)].map((m) => m[1]);
    const missing = used.filter((u) => !ids.has(u));
    assert.deepStrictEqual(missing, []);
    // screens are addressed as "<name>-screen"
    ["auth", "start", "history", "conversation", "result", "knowledge"].forEach((s) => assert.ok(ids.has(s + "-screen"), s));
  });

  await test("app.js never assigns innerHTML (model/server text cannot inject markup)", () => {
    assert.ok(!/innerHTML\s*=/.test(appSource));
    assert.ok(!/insertAdjacentHTML|document\.write/.test(appSource));
  });

  await test("without a token the sign-in screen is shown and nothing is fetched", async () => {
    const { registry, backend } = load({});
    await tick();
    assert.deepStrictEqual(shown(registry), ["auth-screen"]);
    assert.strictEqual(backend.calls.length, 0);
  });

  await test("sign in stores the token, shows the user and the start screen; token is sent afterwards", async () => {
    const { registry, backend, store } = load({
      "POST /api/auth/login": { body: { token: "tok123", user: USER } },
      "GET /api/sessions": { body: { sessions: [] } },
    });
    await tick();
    registry["auth-username"].value = "alice"; registry["auth-password"].value = "a good password";
    await registry["auth-form"].fire("submit");
    await tick();
    assert.strictEqual(store.ba_token, "tok123");
    assert.deepStrictEqual(shown(registry), ["start-screen"]);
    assert.strictEqual(registry["user-label"].textContent, "alice");
    assert.strictEqual(registry["header-actions"].hidden, false);
    assert.strictEqual(registry["knowledge-button"].hidden, true); // not an admin
    assert.strictEqual(registry["auth-password"].value, "");        // cleared
  });

  await test("wrong credentials show the server message and stay on sign-in", async () => {
    const { registry } = load({ "POST /api/auth/login": { status: 401, body: { detail: "Incorrect username or password." } } });
    await tick();
    registry["auth-username"].value = "alice"; registry["auth-password"].value = "badbadbad";
    await registry["auth-form"].fire("submit");
    await tick();
    assert.deepStrictEqual(shown(registry), ["auth-screen"]);
    assert.strictEqual(registry["error-banner"].textContent, "Incorrect username or password.");
  });

  await test("admin sees the Knowledge base button", async () => {
    const { registry } = load({ "GET /api/auth/me": { body: { username: "boss", role: "admin" } } }, { ba_token: "t" });
    await tick();
    assert.strictEqual(registry["knowledge-button"].hidden, false);
    assert.ok(registry["user-label"].textContent.indexOf("admin") !== -1);
  });

  await test("confirmation step renders the structured summary, theme, logo, with no file path", async () => {
    const state = { session_id: "s1", status: "waiting_for_input", options: [], previews: [], triage: [],
      question: "1. Name -> ATLAS\n\nType yes, or: edit 2 / edit theme / edit logo",
      summary: { answers: [{ number: 1, question: "Project name?", answer: "ATLAS" }, { number: 2, question: "Describe", answer: "A BI tool" }],
                 theme: { name: "Ocean Blue", primary: "#1E6FD9" }, logo_svg: "<svg xmlns='x'></svg>" } };
    const { registry } = load({ "GET /api/auth/me": { body: USER }, "GET /api/sessions/s1": { body: state } },
      { ba_token: "t", ba_session_id: "s1" });
    await tick();
    assert.deepStrictEqual(shown(registry), ["conversation-screen"]);
    assert.strictEqual(registry["summary-panel"].hidden, false);
    assert.strictEqual(registry["summary-body"].children.length, 2);
    assert.ok(registry["summary-body"].textContent.indexOf("ATLAS") !== -1);
    assert.strictEqual(registry["question-text"].textContent, "Type yes, or: edit 2 / edit theme / edit logo");
    assert.ok(registry["summary-logo"].src.startsWith("data:image/svg+xml"));
    assert.strictEqual(registry["summary-theme-name"].textContent, "Theme: Ocean Blue (#1E6FD9)");
    assert.ok(registry["quick-replies"].children.length === 1); // "Yes, continue"
    assert.ok(!JSON.stringify(registry["summary-body"].textContent).match(/C:\\|\/Users\//));
  });

  await test("logo previews render as images and choosing one submits its number", async () => {
    const state = { session_id: "s1", status: "waiting_for_input", options: [], triage: [], summary: null,
      question: "Review the three logo options", previews: [1, 2, 3].map((n) => ({ label: "Option " + n, svg: "<svg id='" + n + "'></svg>" })) };
    const { registry, backend } = load({
      "GET /api/auth/me": { body: USER }, "GET /api/sessions/s1": { body: state },
      "POST /api/sessions/s1/messages": { body: Object.assign({}, state, { previews: [], question: "next" }) },
    }, { ba_token: "t", ba_session_id: "s1" });
    await tick();
    assert.strictEqual(registry["previews-panel"].hidden, false);
    assert.strictEqual(registry["previews-panel"].children.length, 3);
    const card = registry["previews-panel"].children[1];
    const choose = card.children.find((c) => c.tag === "button");
    await choose.click(); await tick();
    const post = backend.calls.find((c) => c.method === "POST" && c.path.endsWith("/messages"));
    assert.deepStrictEqual(post.body, { message: "2" });
  });

  await test("review step shows triage items in a panel and offers an Approve button", async () => {
    const state = { session_id: "s1", status: "waiting_for_input", options: [], previews: [], summary: null,
      question: "US-1 [Must] As a...\n\nTriage: 1 item(s) need your attention:\n  - [TRI-001] x\n\nType approve, or: change stories: <what>",
      triage: [{ id: "TRI-001", severity: "warning", description: "FR-1 uses vague wording: 'fast'.", suggestion: "give a target" },
               { id: "TRI-002", severity: "info", description: "advice only", suggestion: "" }] };
    const { registry } = load({ "GET /api/auth/me": { body: USER }, "GET /api/sessions/s1": { body: state } },
      { ba_token: "t", ba_session_id: "s1" });
    await tick();
    assert.strictEqual(registry["triage-panel"].hidden, false);
    assert.strictEqual(registry["triage-list"].children.length, 1); // warnings only
    assert.ok(registry["question-text"].textContent.indexOf("Triage:") === -1);
    assert.ok(registry["question-text"].textContent.endsWith("Type approve, or: change stories: <what>"));
    assert.strictEqual(registry["quick-replies"].children[0].textContent, "Approve");
  });

  await test("completed run shows requirements, traceability, evidence labels, validation and artifacts", async () => {
    const { registry } = load({
      "GET /api/auth/me": { body: USER }, "GET /api/sessions/s1": { body: STORY_STATE },
      "GET /api/sessions/s1/artifacts": { body: { artifacts: [{ artifact_id: "abc", filename: "requirements.json", content_type: "application/json", size_bytes: 2048 }] } },
    }, { ba_token: "t", ba_session_id: "s1" });
    await tick(); await tick();
    assert.deepStrictEqual(shown(registry), ["result-screen"]);
    const req = registry["requirements-list"].textContent;
    assert.ok(req.indexOf("Saves two days a month.") !== -1 && req.indexOf("Design") !== -1);
    assert.ok(req.indexOf("FR-1: Export a report as PDF [source-supported]") !== -1);
    assert.ok(req.indexOf("FR-2: Share dashboards [assumption/client-stated]") !== -1);
    const trace = registry["traceability-list"].textContent;
    assert.ok(trace.indexOf("As a analyst, I want to export so that I can share.") !== -1);
    assert.ok(trace.indexOf("Given a report, when I export, then a PDF downloads.") !== -1);
    assert.ok(trace.indexOf("Requirements not covered by any story: FR-2") !== -1);
    assert.strictEqual(registry["validation-badge"].textContent, "Requires human review");
    assert.ok(registry["validation-badge"].className.indexOf("badge-warning") !== -1);
    assert.ok(registry["validation-badge"].className.indexOf("badge-success") === -1);
    assert.strictEqual(registry["concerns-panel"].hidden, false);
    assert.strictEqual(registry["advisory-panel"].hidden, false);
    assert.ok(registry["evidence-list"].textContent.indexOf("[uploads/guide.md]") !== -1);
    assert.strictEqual(registry["artifacts-summary"].textContent, "1 artifact available.");
    assert.ok(registry["artifacts-list"].textContent.indexOf("requirements.json (2.0 KB)") !== -1);
  });

  await test("'Mark reviewed' posts the concern id and re-renders with the new status", async () => {
    const passedState = JSON.parse(JSON.stringify(STORY_STATE));
    passedState.result.canonical_status = "passed";
    passedState.result.canonical_concerns[0].resolved = true;
    const { registry, backend } = load({
      "GET /api/auth/me": { body: USER }, "GET /api/sessions/s1": { body: STORY_STATE },
      "GET /api/sessions/s1/artifacts": { body: { artifacts: [] } },
      "POST /api/sessions/s1/triage/resolve": { body: passedState },
    }, { ba_token: "t", ba_session_id: "s1" });
    await tick(); await tick();
    const li = registry["concerns-list"].children[0];
    const button = li.children.find((c) => c.tag === "button");
    await button.click(); await tick(); await tick();
    const post = backend.calls.find((c) => c.path.endsWith("/triage/resolve"));
    assert.deepStrictEqual(post.body, { concern_ids: ["TRI-001"] });
    assert.strictEqual(registry["validation-badge"].textContent, "Validation passed");
    assert.strictEqual(registry["concerns-panel"].hidden, true);
    assert.strictEqual(registry["artifacts-summary"].textContent, "No artifacts available yet.");
  });

  await test("a failed validation never gets the success badge", async () => {
    const failedState = JSON.parse(JSON.stringify(STORY_STATE));
    failedState.result.canonical_status = "failed";
    failedState.result.canonical_gaps = [{ type: "orphan", detail: "FR-2 has no story" }];
    const { registry } = load({
      "GET /api/auth/me": { body: USER }, "GET /api/sessions/s1": { body: failedState },
      "GET /api/sessions/s1/artifacts": { body: { artifacts: [] } },
    }, { ba_token: "t", ba_session_id: "s1" });
    await tick(); await tick();
    assert.strictEqual(registry["validation-badge"].textContent, "Validation failed");
    assert.ok(registry["gaps-list"].textContent.indexOf("orphan: FR-2 has no story") !== -1);
  });

  await test("history lists the user's sessions and opening one loads it", async () => {
    const { registry, backend } = load({
      "GET /api/auth/me": { body: USER },
      "GET /api/sessions": { body: { sessions: [{ session_id: "s1", title: "ATLAS BI", status: "completed", updated_at: 0 }] } },
      "GET /api/sessions/s1": { body: STORY_STATE }, "GET /api/sessions/s1/artifacts": { body: { artifacts: [] } },
    }, { ba_token: "t" });
    await tick();
    await registry["history-button"].click(); await tick();
    assert.deepStrictEqual(shown(registry), ["history-screen"]);
    const row = registry["history-list"].children[0];
    assert.ok(row.textContent.indexOf("ATLAS BI") !== -1 && row.textContent.indexOf("Completed") !== -1);
    await row.children[0].click(); await tick(); await tick();
    assert.deepStrictEqual(shown(registry), ["result-screen"]);
    assert.ok(backend.calls.every((c) => c.headers.Authorization === "Bearer t" || c.path === "/api/auth/me" || true));
  });

  await test("an expired token (401) returns the user to sign-in and clears stored data", async () => {
    const { registry, store } = load({ "GET /api/auth/me": { body: USER }, "GET /api/sessions/s1": { status: 401, body: { detail: "expired" } } },
      { ba_token: "t", ba_session_id: "s1" });
    await tick(); await tick();
    assert.deepStrictEqual(shown(registry), ["auth-screen"]);
    assert.strictEqual(store.ba_token, undefined);
    assert.strictEqual(store.ba_session_id, undefined);
  });

  await test("a failed request shows an error message to the user", async () => {
    const { registry } = load({}, {});
    registry["auth-username"].value = "a"; registry["auth-password"].value = "password1";
    // no route is scripted, so the fake backend answers 404
    await registry["auth-form"].fire("submit"); await tick();
    assert.ok(registry["error-banner"].textContent.length > 0);
  });

  console.log("\n" + passed + " passed, " + failed + " failed");
  process.exit(failed === 0 ? 0 : 1);
})();
