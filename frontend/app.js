/**
 * Frontend application logic (DOM + fetch layer).
 *
 * Talks to the backend API (backend/app.py). Every decision that is not
 * about the DOM is delegated to window.BALogic (logic.js), which has its
 * own Node tests (frontend/tests/test_logic.js).
 */
(function () {
  "use strict";

  const API_BASE = BALogic.apiBaseUrl();
  const TOKEN_KEY = "ba_token";
  const SESSION_KEY = "ba_session_id";

  let currentUser = null;
  let currentSessionId = null;
  let authMode = "login"; // or "register"

  const $ = (id) => document.getElementById(id);
  const screens = ["auth", "start", "history", "conversation", "result", "knowledge"];

  function showScreen(name) {
    screens.forEach((s) => { $(s + "-screen").hidden = s !== name; });
  }
  function setLoading(on) { $("loading-indicator").hidden = !on; }
  function showError(msg) { const b = $("error-banner"); b.textContent = msg; b.hidden = false; }
  function clearError() { const b = $("error-banner"); b.textContent = ""; b.hidden = true; }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }

  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  // ---------------------------------------------------------------- API helper
  class ApiError extends Error {
    constructor(message, status) { super(message); this.status = status; }
  }

  async function apiFetch(path, options) {
    const opts = Object.assign({}, options || {});
    opts.headers = Object.assign({ "Content-Type": "application/json" },
      BALogic.authHeaders(localStorage.getItem(TOKEN_KEY)), opts.headers || {});
    let response;
    try {
      response = await fetch(API_BASE + path, opts);
    } catch (e) {
      throw new ApiError("Cannot reach the server. Is the backend running?", 0);
    }
    let body = null;
    try { body = await response.json(); } catch (e) { /* not JSON */ }
    if (response.status === 401 && path.indexOf("/api/auth/") !== 0) {
      signedOut("Your session has expired. Please sign in again.");
      throw new ApiError("Please sign in again.", 401);
    }
    if (!response.ok) {
      throw new ApiError(body && body.detail ? String(body.detail) : "Request failed (" + response.status + ")",
        response.status);
    }
    return body;
  }

  // ------------------------------------------------------------ authentication
  function signedOut(message) {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(SESSION_KEY);
    currentUser = null;
    currentSessionId = null;
    $("header-actions").hidden = true;
    showScreen("auth");
    if (message) showError(message);
  }

  function signedIn(user) {
    currentUser = user;
    $("header-actions").hidden = false;
    $("user-label").textContent = user.username + (user.role === "admin" ? " (admin)" : "");
    $("knowledge-button").hidden = user.role !== "admin";
  }

  function setAuthMode(mode) {
    authMode = mode;
    const reg = mode === "register";
    $("auth-title").textContent = reg ? "Create an account" : "Sign in";
    $("auth-submit").textContent = reg ? "Create account" : "Sign in";
    $("auth-toggle").textContent = reg ? "I already have an account" : "Create an account";
    $("auth-password").autocomplete = reg ? "new-password" : "current-password";
  }

  async function submitAuth(ev) {
    ev.preventDefault();
    clearError();
    setLoading(true);
    try {
      const data = await apiFetch(authMode === "register" ? "/api/auth/register" : "/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: $("auth-username").value.trim(), password: $("auth-password").value }),
      });
      localStorage.setItem(TOKEN_KEY, data.token);
      $("auth-password").value = "";
      signedIn(data.user);
      await showStartOrResume();
    } catch (e) {
      showError(e.message);
    } finally { setLoading(false); }
  }

  async function logout() {
    try { await apiFetch("/api/auth/logout", { method: "POST" }); } catch (e) { /* ignore */ }
    signedOut();
  }

  // -------------------------------------------------------------- conversation
  function renderSummary(summary) {
    const panel = $("summary-panel");
    if (!summary) { panel.hidden = true; return; }
    panel.hidden = false;
    const body = $("summary-body");
    clear(body);
    (summary.answers || []).forEach((row) => {
      const tr = document.createElement("tr");
      tr.appendChild(el("th", row.number + ". " + row.question));
      tr.appendChild(el("td", row.answer));
      body.appendChild(tr);
    });
    const theme = summary.theme || {};
    $("summary-swatch").style.background = /^#[0-9a-fA-F]{3,8}$/.test(theme.primary || "") ? theme.primary : "transparent";
    $("summary-theme-name").textContent = "Theme: " + (theme.name || "") + (theme.primary ? " (" + theme.primary + ")" : "");
    const uri = BALogic.svgToDataUri(summary.logo_svg);
    $("summary-logo").hidden = !uri;
    if (uri) $("summary-logo").src = uri;
  }

  function renderPreviews(previews) {
    const box = $("previews-panel");
    clear(box);
    box.hidden = !(previews && previews.length);
    (previews || []).forEach((p, i) => {
      const card = el("div", null, "preview-card");
      const uri = BALogic.svgToDataUri(p.svg);
      if (uri) {
        const img = document.createElement("img");
        img.src = uri; img.alt = p.label || ("Logo option " + (i + 1)); img.className = "logo-preview";
        card.appendChild(img);
      }
      card.appendChild(el("div", p.label || ("Option " + (i + 1))));
      const btn = el("button", "Choose " + (i + 1), "option-button");
      btn.type = "button";
      btn.addEventListener("click", () => submitAnswer(String(i + 1)));
      card.appendChild(btn);
      box.appendChild(card);
    });
  }

  function renderTriageList(listEl, items) {
    clear(listEl);
    items.forEach((f) => {
      const li = el("li");
      li.appendChild(el("span", f.severity === "info" ? "Advice" : "Review", "tag tag-" + (f.severity === "info" ? "info" : "warning")));
      li.appendChild(document.createTextNode(" " + (f.description || "")));
      if (f.suggestion) li.appendChild(el("div", f.suggestion, "muted"));
      listEl.appendChild(li);
    });
  }

  function renderQuestion(state) {
    const hasSummary = !!state.summary;
    // With a structured summary the web UI shows only the instruction line;
    // the full text is for the command-line interface.
    const hasTriage = (state.triage || []).some((f) => f.severity === "warning");
    $("question-text").textContent = hasSummary ? BALogic.instructionLine(state.question)
      : hasTriage ? BALogic.stripTriageText(state.question) : (state.question || "");
    renderSummary(state.summary);
    renderPreviews(state.previews);

    const triage = (state.triage || []).filter((f) => f.severity === "warning");
    $("triage-panel").hidden = triage.length === 0;
    renderTriageList($("triage-list"), triage);

    const opts = $("options-container");
    clear(opts);
    (state.options || []).forEach((opt) => {
      const b = el("button", opt, "option-button");
      b.type = "button";
      b.addEventListener("click", () => submitAnswer(opt));
      opts.appendChild(b);
    });
    const quick = $("quick-replies");
    clear(quick);
    BALogic.quickReplies(state).forEach((q) => {
      const b = el("button", q === "yes" ? "Yes, continue" : "Approve", "primary-button");
      b.type = "button";
      b.addEventListener("click", () => submitAnswer(q));
      quick.appendChild(b);
    });
  }

  // ------------------------------------------------------------------- result
  function listSection(container, title, items) {
    if (!items || !items.length) return;
    container.appendChild(el("h3", title));
    const ul = document.createElement("ul");
    items.forEach((it) => ul.appendChild(el("li", typeof it === "string" ? it : JSON.stringify(it))));
    container.appendChild(ul);
  }

  function renderRequirements(result) {
    const box = $("requirements-list");
    clear(box);
    const a = result.analysis;
    if (!a) return;
    if (result.business_case) {
      box.appendChild(el("h3", "Business case"));
      box.appendChild(el("p", result.business_case));
    }
    listSection(box, "Objectives", a.objectives);
    listSection(box, "Stakeholders", a.stakeholders);
    listSection(box, "Tasks and milestones", result.tasks);
    listSection(box, "Risks", a.risks);
    listSection(box, "Data entities", a.data_entities);
    if (a.scope) { listSection(box, "In scope", a.scope.in); listSection(box, "Out of scope", a.scope.out); }
    if (a.functional_requirements && a.functional_requirements.length) {
      box.appendChild(el("h3", "Functional requirements"));
      const ul = document.createElement("ul");
      a.functional_requirements.forEach((fr) => {
        const kind = BALogic.classifyRequirementEvidence(fr);
        ul.appendChild(el("li", (fr.id || "") + ": " + (fr.text || "") +
          (kind === "source-supported" ? " [source-supported]" : " [assumption/client-stated]")));
      });
      box.appendChild(ul);
    }
    listSection(box, "Non-functional requirements", a.non_functional_requirements);
  }

  function renderTraceability(result) {
    const box = $("traceability-list");
    clear(box);
    const frs = result.analysis ? result.analysis.functional_requirements : [];
    const t = BALogic.buildTraceability(frs, result.stories, result.criteria);
    if (!t.stories.length) { box.appendChild(el("p", "No user stories were generated.", "muted")); return; }
    t.stories.forEach((st) => {
      const card = el("article", null, "story-card");
      card.appendChild(el("h4", st.id + (st.priority ? " (" + st.priority + ")" : "")));
      card.appendChild(el("p", "As a " + st.as_a + ", I want " + st.i_want + " so that " + st.so_that + "."));
      const links = el("p", null, "muted");
      links.appendChild(document.createTextNode("Implements: "));
      st.requirements.forEach((r, i) => {
        links.appendChild(el("span", r.id, "tag tag-info"));
        links.appendChild(document.createTextNode(" " + r.text + (i < st.requirements.length - 1 ? "; " : "")));
      });
      card.appendChild(links);
      if (st.missingCriteria) {
        card.appendChild(el("p", "No acceptance criteria.", "muted"));
      } else {
        const ul = document.createElement("ul");
        st.criteria.forEach((c) => ul.appendChild(el("li", "Given " + c.given + ", when " + c.when + ", then " + c.then + ".")));
        card.appendChild(ul);
      }
      box.appendChild(card);
    });
    if (t.uncoveredRequirements.length) {
      box.appendChild(el("p", "Requirements not covered by any story: " +
        t.uncoveredRequirements.map((r) => r.id).join(", "), "error-text"));
    }
  }

  function renderValidation(result) {
    const badge = BALogic.formatValidationBadge(result.canonical_status);
    $("validation-badge").textContent = badge.label;
    $("validation-badge").className = "badge " + badge.cssClass;
    const gaps = $("gaps-list");
    clear(gaps);
    const list = result.canonical_gaps || [];
    if (!list.length) gaps.appendChild(el("li", "No structural gaps reported."));
    list.forEach((g) => gaps.appendChild(el("li", (g.type || "gap") + ": " + (g.detail || ""))));
    if (result.canonical_error) gaps.appendChild(el("li", "Validation could not run: " + result.canonical_error));

    const t = BALogic.splitTriage(result);
    $("concerns-panel").hidden = t.open.length === 0;
    renderTriageList($("concerns-list"), t.open);
    // one button per open concern
    Array.from($("concerns-list").children).forEach((li, i) => {
      const b = el("button", "Mark reviewed", "secondary-button small");
      b.type = "button";
      b.addEventListener("click", () => resolveTriage([t.open[i].id]));
      li.appendChild(b);
    });
    $("advisory-panel").hidden = t.advisory.length === 0;
    renderTriageList($("advisory-list"), t.advisory);
  }

  function renderEvidence(evidence) {
    const ul = $("evidence-list");
    clear(ul);
    if (!evidence || !evidence.length) {
      ul.appendChild(el("li", "No knowledge-base evidence was retrieved for this project."));
      return;
    }
    evidence.forEach((c) => ul.appendChild(el("li", "[" + c.source + "] " + c.text)));
  }

  async function renderArtifacts(sessionId) {
    const data = await apiFetch("/api/sessions/" + sessionId + "/artifacts");
    const artifacts = data.artifacts || [];
    $("artifacts-summary").textContent = BALogic.summarizeArtifactCount(artifacts);
    const ul = $("artifacts-list");
    clear(ul);
    artifacts.forEach((a) => {
      const li = document.createElement("li");
      const btn = el("button", a.filename + " (" + BALogic.formatBytes(a.size_bytes) + ")", "link-button");
      btn.type = "button";
      btn.addEventListener("click", () => downloadArtifact(sessionId, a));
      li.appendChild(btn);
      ul.appendChild(li);
    });
  }

  async function downloadArtifact(sessionId, artifact) {
    clearError();
    try {
      const response = await fetch(API_BASE + "/api/sessions/" + sessionId + "/artifacts/" + artifact.artifact_id,
        { headers: BALogic.authHeaders(localStorage.getItem(TOKEN_KEY)) });
      if (!response.ok) throw new ApiError("Download failed (" + response.status + ")", response.status);
      const url = URL.createObjectURL(await response.blob());
      const a = document.createElement("a");
      a.href = url; a.download = artifact.filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { showError(e.message); }
  }

  function renderState(state) {
    currentSessionId = state.session_id;
    localStorage.setItem(SESSION_KEY, state.session_id);
    if (BALogic.isSessionActive(state.status)) {
      showScreen("conversation");
      renderQuestion(state);
    } else if (BALogic.isSessionComplete(state.status)) {
      showScreen("result");
      const result = state.result || {};
      renderRequirements(result);
      renderTraceability(result);
      renderValidation(result);
      renderEvidence(result.retrieved_evidence);
      renderArtifacts(state.session_id).catch((e) => showError("Could not load artifacts: " + e.message));
    } else if (state.status === "error") {
      showScreen("conversation");
      showError(state.error || "The workflow reported an error.");
    }
  }

  // ------------------------------------------------------------------ actions
  async function startSession() {
    clearError(); setLoading(true);
    try { renderState(await apiFetch("/api/sessions", { method: "POST" })); }
    catch (e) { showError("Could not start a session: " + e.message); }
    finally { setLoading(false); }
  }

  async function submitAnswer(message) {
    if (!currentSessionId) { showError("No active session."); return; }
    clearError(); setLoading(true);
    try {
      renderState(await apiFetch("/api/sessions/" + currentSessionId + "/messages",
        { method: "POST", body: JSON.stringify({ message: message }) }));
    } catch (e) { showError("Could not submit your answer: " + e.message); }
    finally { setLoading(false); $("answer-input").value = ""; }
  }

  async function resolveTriage(ids) {
    clearError(); setLoading(true);
    try {
      renderState(await apiFetch("/api/sessions/" + currentSessionId + "/triage/resolve",
        { method: "POST", body: JSON.stringify({ concern_ids: ids }) }));
    } catch (e) { showError("Could not update the review: " + e.message); }
    finally { setLoading(false); }
  }

  async function openSession(sessionId) {
    clearError(); setLoading(true);
    try { renderState(await apiFetch("/api/sessions/" + sessionId)); }
    catch (e) { showError("Could not open that session: " + e.message); }
    finally { setLoading(false); }
  }

  async function showHistory() {
    clearError(); setLoading(true);
    try {
      const data = await apiFetch("/api/sessions");
      const ul = $("history-list");
      clear(ul);
      const items = data.sessions || [];
      $("history-empty").hidden = items.length > 0;
      items.forEach((s) => {
        const li = document.createElement("li");
        const btn = el("button", s.title, "link-button");
        btn.type = "button";
        btn.addEventListener("click", () => openSession(s.session_id));
        li.appendChild(btn);
        li.appendChild(el("span", " — " + BALogic.statusLabel(s.status) + ", " + BALogic.formatTimestamp(s.updated_at), "muted"));
        ul.appendChild(li);
      });
      showScreen("history");
    } catch (e) { showError(e.message); }
    finally { setLoading(false); }
  }

  async function showStartOrResume() {
    const saved = localStorage.getItem(SESSION_KEY);
    if (saved) {
      try { renderState(await apiFetch("/api/sessions/" + saved)); return; }
      catch (e) {
        if (e.status === 401) return;  // token expired: apiFetch already returned the user to sign-in
        localStorage.removeItem(SESSION_KEY);
      }
    }
    showScreen("start");
  }

  // --------------------------------------------------------------- knowledge
  async function showKnowledge() {
    clearError(); setLoading(true);
    try {
      const data = await apiFetch("/api/knowledge/documents");
      const ul = $("knowledge-list");
      clear(ul);
      (data.documents || []).forEach((d) =>
        ul.appendChild(el("li", d.source + " (" + BALogic.formatBytes(d.size_bytes) + ")")));
      $("knowledge-message").textContent = "";
      showScreen("knowledge");
    } catch (e) { showError(e.message); }
    finally { setLoading(false); }
  }

  function readAsBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
      reader.onerror = () => reject(new Error("Could not read the file."));
      reader.readAsDataURL(file);
    });
  }

  async function uploadKnowledge(ev) {
    ev.preventDefault();
    const file = $("knowledge-file").files[0];
    if (!file) return;
    clearError(); setLoading(true);
    try {
      const result = await apiFetch("/api/knowledge/documents", {
        method: "POST", body: JSON.stringify({ filename: file.name, content_base64: await readAsBase64(file) }),
      });
      $("knowledge-message").textContent = result.source + ": " + result.status + " (" + result.chunks + " chunks).";
      $("knowledge-file").value = "";
      await showKnowledge();
      $("knowledge-message").textContent = result.source + ": " + result.status + " (" + result.chunks + " chunks).";
    } catch (e) { showError(e.message); }
    finally { setLoading(false); }
  }

  // --------------------------------------------------------------------- init
  $("auth-form").addEventListener("submit", submitAuth);
  $("auth-toggle").addEventListener("click", () => setAuthMode(authMode === "login" ? "register" : "login"));
  $("logout-button").addEventListener("click", logout);
  $("start-button").addEventListener("click", startSession);
  $("history-button").addEventListener("click", showHistory);
  $("new-session-button").addEventListener("click", () => { localStorage.removeItem(SESSION_KEY); clearError(); showScreen("start"); });
  $("knowledge-button").addEventListener("click", showKnowledge);
  $("knowledge-form").addEventListener("submit", uploadKnowledge);
  $("resolve-all-button").addEventListener("click", () => resolveTriage("all"));
  $("answer-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const v = $("answer-input").value.trim();
    if (v) submitAnswer(v);
  });

  (async function init() {
    if (!localStorage.getItem(TOKEN_KEY)) { showScreen("auth"); return; }
    setLoading(true);
    try {
      signedIn(await apiFetch("/api/auth/me"));
      await showStartOrResume();
    } catch (e) { signedOut(); }
    finally { setLoading(false); }
  })();
})();
