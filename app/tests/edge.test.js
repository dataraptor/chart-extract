/**
 * Split 09 — T1: the edge-state view-model. Pure `map.js` unit tests for the descriptors that drive
 * the designed failure/unusual-input states: envelope `type` → notice, the no-text-layer signal,
 * the ambiguous "1 of N" tag, the misroute hint, and the ListField group header. Deterministic,
 * no network — the same `node --test` floor as Split 07's `map.test.js`.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const Map = require("../map.js");

const FX = path.join(__dirname, "fixtures");
function fixture(name) {
  return JSON.parse(fs.readFileSync(path.join(FX, name), "utf8"));
}
function byName(rows) {
  return Object.fromEntries(rows.map((r) => [r.name, r]));
}

// --- toNotice: each envelope type → its designed notice -----------------------

test("toNotice: every error type maps to the correct designed notice", () => {
  const cases = {
    no_text_layer: { kind: "warning", blocking: false, copy: /highlighting disabled/i },
    refusal: { kind: "neutral", blocking: false, copy: /safety classifier/i },
    truncated: { kind: "info", blocking: false, copy: /truncated/i },
    unknown_doc_type: { kind: "warning", blocking: true, copy: /choose a schema/i },
    unsupported_file: { kind: "error", blocking: false, copy: /\.txt only/i },
    missing_api_key: { kind: "info", blocking: false, copy: /offline/i },
  };
  for (const [type, want] of Object.entries(cases)) {
    const n = Map.toNotice({ type, message: "server msg", hint: "do this" });
    assert.equal(n.type, type, `type carried for ${type}`);
    assert.equal(n.kind, want.kind, `kind for ${type}`);
    assert.equal(n.blocking, want.blocking, `blocking for ${type}`);
    assert.match(n.title + " " + n.body, want.copy, `copy for ${type}`);
    assert.equal(n.hint, "do this");
  }
});

test("toNotice: unknown_doc_type is the only blocking notice", () => {
  assert.equal(Map.toNotice({ type: "unknown_doc_type" }).blocking, true);
  for (const type of ["no_text_layer", "refusal", "truncated", "unsupported_file", "missing_api_key"]) {
    assert.equal(Map.toNotice({ type }).blocking, false);
  }
});

test("toNotice: an unknown type falls back to a recoverable error carrying the server message", () => {
  const n = Map.toNotice({ type: "weird", message: "boom" });
  assert.equal(n.kind, "error");
  assert.equal(n.body, "boom");
  assert.equal(n.blocking, false);
});

test("toNotice: network error reads as the offline notice", () => {
  const n = Map.toNotice({ type: "network", message: "unreachable" });
  assert.equal(n.kind, "info");
  assert.match(n.title, /offline/i);
});

// --- no-text-layer: rows marked, no ranges -----------------------------------

test("highlight_available:false → rows flagged highlightNA, no ranges produced", () => {
  const result = {
    highlight_available: false,
    fields: [
      { name: "specimen", value: "x", char_start: null, char_end: null, match_quality: "none", flag: null },
      { name: "diagnosis", value: "y", char_start: null, char_end: null, match_quality: "none", flag: null },
    ],
  };
  assert.equal(Map.highlightDisabled(result), true);
  const rows = Map.toFieldRows(result);
  assert.ok(rows.every((r) => r.highlightNA === true));
  // values still render (extraction ran) — only the grounding highlight is gone.
  assert.deepEqual(rows.map((r) => r.value), ["x", "y"]);
  assert.deepEqual(Map.toHighlightRanges(result), []);
});

test("a normal result is not highlight-disabled", () => {
  const pathResult = fixture("extract_path.json");
  assert.equal(Map.highlightDisabled(pathResult), false);
  assert.ok(Map.toFieldRows(pathResult).every((r) => r.highlightNA === false));
  assert.ok(Map.toHighlightRanges(pathResult).length > 0);
});

// --- ambiguous "1 of N" -------------------------------------------------------

test("ambiguous_span field → row carries the match count for the '1 of N' tag", () => {
  const result = {
    fields: [
      {
        name: "er_status",
        value: "positive",
        source_span: "positive",
        char_start: 200,
        char_end: 208,
        match_quality: "exact",
        n_matches: 2,
        flag: "ambiguous_span",
        confidence: 0.92,
      },
    ],
  };
  const r = byName(Map.toFieldRows(result)).er_status;
  assert.equal(r.flag, "ambiguous_span");
  assert.equal(r.count, 2); // the N in "1 of N"
  // still highlightable (the first match) with the dotted-underline flag downstream.
  const ranges = Map.toHighlightRanges(result);
  assert.equal(ranges.length, 1);
  assert.equal(ranges[0].flag, "ambiguous_span");
});

// --- misroute hint ------------------------------------------------------------

test("isMisrouted: mostly-ungrounded result fires the hint; a healthy one does not", () => {
  const misrouted = {
    fields: Array.from({ length: 9 }, (_, i) => ({
      name: "f" + i,
      value: i === 0 ? "kept" : null,
      flag: i === 0 ? null : i % 2 ? "not_found" : "not_grounded",
    })),
  };
  assert.equal(Map.isMisrouted(misrouted), true);
  assert.equal(Map.isMisrouted(fixture("extract_path.json")), false);
  assert.equal(Map.isMisrouted(fixture("extract_intake.json")), false);
  assert.equal(Map.isMisrouted({ fields: [] }), false);
});

// --- ListField grouping -------------------------------------------------------

test("toListGroups: intake result → medications/allergies headers with k of n grounded · m review", () => {
  const rows = Map.toFieldRows(fixture("extract_intake.json"));
  const groups = Map.toListGroups(rows);
  const byBase = Object.fromEntries(groups.map((g) => [g.name, g]));

  assert.ok("medications" in byBase, "medications group present");
  const meds = byBase.medications;
  assert.equal(meds.total, 3);
  assert.equal(meds.grounded, 3);
  assert.equal(meds.review, 0);
  assert.equal(meds.label, "medications · 3 of 3 grounded");
  assert.deepEqual(meds.items, ["medications[0]", "medications[1]", "medications[2]"]);

  // scalar rows (patient_name, pcp, …) never become groups.
  assert.ok(!("patient_name" in byBase));
});

test("toListGroups: review count surfaces in the label when an item needs review", () => {
  const rows = [
    { name: "medications[0]", value: "A", flag: null },
    { name: "medications[1]", value: "B", flag: "needs_review" },
    { name: "medications[2]", value: null, flag: "not_found" },
  ];
  const g = Map.toListGroups(rows)[0];
  assert.equal(g.total, 3);
  assert.equal(g.grounded, 2);
  assert.equal(g.review, 1);
  assert.equal(g.label, "medications · 2 of 3 grounded · 1 review");
});

// --- totality -----------------------------------------------------------------

test("edge mappers are total: empty/undefined input never throws", () => {
  assert.doesNotThrow(() => Map.toNotice(undefined));
  assert.doesNotThrow(() => Map.isMisrouted(undefined));
  assert.doesNotThrow(() => Map.toListGroups(undefined));
  assert.deepEqual(Map.toListGroups(undefined), []);
  assert.equal(Map.highlightDisabled(undefined), false);
});
