
const assert = require("assert");
const path = require("path");
const BALogic = require(path.join(__dirname, "..", "logic.js"));

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log("ok - " + name);
  } catch (e) {
    failed += 1;
    console.log("FAIL - " + name + ": " + e.message);
  }
}

// --- formatValidationBadge ---
test("passed status gets success badge", () => {
  const b = BALogic.formatValidationBadge("passed");
  assert.strictEqual(b.cssClass, "badge-success");
});

test("requires_human_review never gets success badge", () => {
  const b = BALogic.formatValidationBadge("requires_human_review");
  assert.notStrictEqual(b.cssClass, "badge-success");
});

test("failed never gets success badge", () => {
  const b = BALogic.formatValidationBadge("failed");
  assert.notStrictEqual(b.cssClass, "badge-success");
});

test("mapping_error never gets success badge", () => {
  const b = BALogic.formatValidationBadge("mapping_error");
  assert.notStrictEqual(b.cssClass, "badge-success");
});

test("null/undefined status never gets success badge", () => {
  assert.notStrictEqual(BALogic.formatValidationBadge(null).cssClass, "badge-success");
  assert.notStrictEqual(BALogic.formatValidationBadge(undefined).cssClass, "badge-success");
});

test("unrecognized status never gets success badge", () => {
  const b = BALogic.formatValidationBadge("totally_unknown_value");
  assert.notStrictEqual(b.cssClass, "badge-success");
  assert.ok(b.label.indexOf("totally_unknown_value") !== -1);
});

// --- classifyRequirementEvidence ---
test("FR with non-empty source_refs is source-supported", () => {
  const result = BALogic.classifyRequirementEvidence({
    text: "x", source_refs: [{ source: "a.md", chunk_id: "1" }],
  });
  assert.strictEqual(result, "source-supported");
});

test("FR with empty source_refs is assumption-or-client-stated", () => {
  const result = BALogic.classifyRequirementEvidence({ text: "x", source_refs: [] });
  assert.strictEqual(result, "assumption-or-client-stated");
});

test("FR with no source_refs key is assumption-or-client-stated", () => {
  const result = BALogic.classifyRequirementEvidence({ text: "x" });
  assert.strictEqual(result, "assumption-or-client-stated");
});

test("FR with source_refs as non-array is treated as assumption, not crash", () => {
  const result = BALogic.classifyRequirementEvidence({ text: "x", source_refs: "oops" });
  assert.strictEqual(result, "assumption-or-client-stated");
});

// --- session status helpers ---
test("isSessionActive true only for waiting_for_input", () => {
  assert.strictEqual(BALogic.isSessionActive("waiting_for_input"), true);
  assert.strictEqual(BALogic.isSessionActive("completed"), false);
  assert.strictEqual(BALogic.isSessionActive("error"), false);
});

test("isSessionComplete true only for completed", () => {
  assert.strictEqual(BALogic.isSessionComplete("completed"), true);
  assert.strictEqual(BALogic.isSessionComplete("waiting_for_input"), false);
});

// --- summarizeArtifactCount ---
test("empty artifact list gives honest 'no artifacts' message", () => {
  assert.strictEqual(BALogic.summarizeArtifactCount([]), "No artifacts available yet.");
  assert.strictEqual(BALogic.summarizeArtifactCount(null), "No artifacts available yet.");
});

test("singular vs plural artifact count wording", () => {
  assert.strictEqual(BALogic.summarizeArtifactCount([{}]), "1 artifact available.");
  assert.strictEqual(BALogic.summarizeArtifactCount([{}, {}]), "2 artifacts available.");
});

// --- formatBytes ---
test("formatBytes handles bytes, KB, MB ranges", () => {
  assert.strictEqual(BALogic.formatBytes(500), "500 B");
  assert.strictEqual(BALogic.formatBytes(2048), "2.0 KB");
  assert.strictEqual(BALogic.formatBytes(5 * 1024 * 1024), "5.0 MB");
});

test("formatBytes rejects negative/invalid input", () => {
  assert.strictEqual(BALogic.formatBytes(-1), "");
  assert.strictEqual(BALogic.formatBytes("not a number"), "");
});


// --- buildTraceability ---
const FRS = [{ id: "FR-1", text: "Login" }, { id: "FR-2", text: "Export" }, { id: "FR-3", text: "Search" }];
const STORIES = [
  { id: "US-1", as_a: "user", i_want: "to log in", so_that: "I can work", fr_ids: ["FR-1"], priority: "Must" },
  { id: "US-2", as_a: "user", i_want: "to export", so_that: "I can share", fr_ids: ["FR-2", "FR-404"] },
];
// NOTE: both stories reuse the same criterion ids, like real agent output.
const CRITERIA = [
  { id: "AC-1", story_id: "US-1", given: "g1", when: "w1", then: "t1" },
  { id: "AC-1", story_id: "US-2", given: "g2", when: "w2", then: "t2" },
  { id: "AC-2", story_id: "US-2", given: "g3", when: "w3", then: "t3" },
];

test("criteria are grouped by story_id even when AC ids repeat", () => {
  const t = BALogic.buildTraceability(FRS, STORIES, CRITERIA);
  assert.strictEqual(t.stories[0].criteria.length, 1);
  assert.strictEqual(t.stories[1].criteria.length, 2);
});

test("story links resolve to requirement text, unknown ids flagged not found", () => {
  const t = BALogic.buildTraceability(FRS, STORIES, CRITERIA);
  assert.strictEqual(t.stories[0].requirements[0].text, "Login");
  assert.strictEqual(t.stories[1].requirements[1].found, false);
});

test("requirements with no story are reported as uncovered", () => {
  const t = BALogic.buildTraceability(FRS, STORIES, CRITERIA);
  assert.deepStrictEqual(t.uncoveredRequirements.map((r) => r.id), ["FR-3"]);
});

test("a story with no criteria is marked missingCriteria", () => {
  const t = BALogic.buildTraceability(FRS, STORIES, []);
  assert.strictEqual(t.stories[0].missingCriteria, true);
});

test("buildTraceability tolerates missing/invalid inputs", () => {
  const t = BALogic.buildTraceability(null, undefined, "x");
  assert.deepStrictEqual(t, { stories: [], uncoveredRequirements: [] });
});

// --- svgToDataUri ---
test("svgToDataUri accepts real svg and encodes it", () => {
  const u = BALogic.svgToDataUri('  <svg xmlns="x"><rect/></svg>');
  assert.ok(u.startsWith("data:image/svg+xml;charset=utf-8,"));
  assert.ok(u.indexOf("%3Csvg") !== -1);
});

test("svgToDataUri rejects non-svg and non-strings", () => {
  assert.strictEqual(BALogic.svgToDataUri("<script>alert(1)</script>"), "");
  assert.strictEqual(BALogic.svgToDataUri(null), "");
  assert.strictEqual(BALogic.svgToDataUri(42), "");
});

// --- authHeaders ---
test("authHeaders builds bearer header only when a token exists", () => {
  assert.deepStrictEqual(BALogic.authHeaders("abc"), { Authorization: "Bearer abc" });
  assert.deepStrictEqual(BALogic.authHeaders(null), {});
  assert.deepStrictEqual(BALogic.authHeaders(""), {});
});

// --- instructionLine / quickReplies ---
test("instructionLine returns the last paragraph", () => {
  assert.strictEqual(BALogic.instructionLine("a\nb\n\nType yes, or: edit 2"), "Type yes, or: edit 2");
  assert.strictEqual(BALogic.instructionLine(""), "");
  assert.strictEqual(BALogic.instructionLine(null), "");
});

test("quickReplies: yes for confirmation summary, approve for review, else none", () => {
  assert.deepStrictEqual(BALogic.quickReplies({ summary: {}, question: "x" }), ["yes"]);
  assert.deepStrictEqual(BALogic.quickReplies({ question: "...\n\nType approve, or: change stories: <what>" }), ["approve"]);
  assert.deepStrictEqual(BALogic.quickReplies({ question: "What is your name?" }), []);
  assert.deepStrictEqual(BALogic.quickReplies(null), []);
});

test("stripTriageText removes the Triage block but keeps story lines and the instruction", () => {
  const q = "US-1 [Must] As a user...\n\nTriage: 1 item(s) need your attention:\n  - [TRI-001] x\n\nType approve, or: change stories: <what>";
  const out = BALogic.stripTriageText(q);
  assert.ok(out.indexOf("Triage:") === -1 && out.indexOf("TRI-001") === -1);
  assert.ok(out.indexOf("US-1") !== -1);
  assert.ok(out.endsWith("Type approve, or: change stories: <what>"));
  assert.strictEqual(BALogic.stripTriageText("no triage here"), "no triage here");
});

// --- splitTriage ---
test("splitTriage separates open, resolved and advisory items", () => {
  const out = BALogic.splitTriage({
    canonical_concerns: [{ id: "TRI-001", resolved: false }, { id: "TRI-002", resolved: true }],
    triage_findings: [{ id: "TRI-001", severity: "warning" }, { id: "TRI-003", severity: "info" }],
  });
  assert.deepStrictEqual(out.open.map((c) => c.id), ["TRI-001"]);
  assert.deepStrictEqual(out.resolved.map((c) => c.id), ["TRI-002"]);
  assert.deepStrictEqual(out.advisory.map((c) => c.id), ["TRI-003"]);
});

test("splitTriage handles an empty result", () => {
  const out = BALogic.splitTriage(null);
  assert.deepStrictEqual(out, { open: [], resolved: [], advisory: [] });
});

// --- timestamps and labels ---
test("formatTimestamp is deterministic UTC", () => {
  assert.strictEqual(BALogic.formatTimestamp(0), "1970-01-01 00:00 UTC");
  assert.strictEqual(BALogic.formatTimestamp("x"), "");
});

test("statusLabel maps known statuses", () => {
  assert.strictEqual(BALogic.statusLabel("completed"), "Completed");
  assert.strictEqual(BALogic.statusLabel("waiting_for_input"), "In progress");
  assert.strictEqual(BALogic.statusLabel("error"), "Error");
});

console.log("\n" + passed + " passed, " + failed + " failed");
process.exit(failed === 0 ? 0 : 1);
