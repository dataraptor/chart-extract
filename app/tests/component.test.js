/**
 * Split 09 — T1: the `Component` render path over the edge states (headless, deterministic).
 *
 * Drives the real `renderVals()` from `ChartExtract.dc.html` through the `_component.js` shim and
 * asserts the designed states surface correctly: no-text-layer banner + highlight-n/a rows,
 * per-type notices (refusal/truncation/unknown), the route-block furniture, the misroute hint, the
 * ListField group header + collapse, and the offline chip. Catches runtime errors the e2e would
 * (no browser needed). The bindings checked here are exactly what the DC template renders.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { loadComponent, walk, textOf } = require("./_component.js");

const FX = path.join(__dirname, "fixtures");
function fixture(name) {
  return JSON.parse(fs.readFileSync(path.join(FX, name), "utf8"));
}
const pathResult = fixture("extract_path.json");
const intakeResult = fixture("extract_intake.json");

/** Build a component already in live mode with `state` applied, and render. */
function render(state) {
  const { component } = loadComponent();
  component.state = Object.assign(
    {
      view: "extraction",
      sample: "pathology",
      revealed: 99,
      streaming: false,
      done: true,
      active: null,
      pinned: [],
      showJSON: false,
      showCaught: false,
      mode: "live",
      result: null,
      docText: "",
      samples: [],
      evalReport: null,
      loading: false,
      apiError: null,
      simulate: null,
      routeBlocked: false,
      truncRetry: false,
      collapsed: [],
    },
    state
  );
  return { component, vals: component.renderVals() };
}

function notice(vals) {
  return walk(vals.documentBody).find((n) => n.props && n.props["data-testid"] === "notice");
}

// --- no-text-layer ------------------------------------------------------------

test("no-text-layer result → warning banner, highlight-n/a rows, no doc marks", () => {
  const result = JSON.parse(JSON.stringify(pathResult));
  result.highlight_available = false;
  result.fields.forEach((f) => {
    f.char_start = null;
    f.char_end = null;
    f.match_quality = "none";
  });
  const { vals } = render({ result, docText: "SPECIMEN: Left breast core biopsy." });

  // the doc-pane header flips to "no text layer"
  assert.equal(vals.docLayerLabel, "no text layer");
  // every field row is marked highlight-n/a with a non-pointer cursor
  assert.ok(vals.fields.length > 0);
  assert.ok(vals.fields.every((r) => r.highlightNA === true));
  assert.ok(vals.fields.every((r) => r.cursor === "default"));
  // values still render (extraction ran)
  assert.ok(vals.fields.some((r) => r.valueDisplay && r.valueDisplay !== "—"));
  // the banner is present with the spec copy; no <mark> nodes are produced
  const all = walk(vals.documentBody);
  const banner = all.find((n) => n.props && n.props["data-notice-type"] === "no_text_layer");
  assert.ok(banner, "no-text-layer banner present");
  assert.match(textOf(banner), /highlighting disabled/i);
  assert.equal(all.filter((n) => n.type === "mark").length, 0);
});

// --- per-type notices ---------------------------------------------------------

test("refusal envelope → calm neutral skip notice (no crash, no blank)", () => {
  const { vals } = render({ apiError: { type: "refusal", message: "skipped" } });
  const n = notice(vals);
  assert.ok(n, "notice rendered");
  assert.equal(n.props["data-notice-type"], "refusal");
  assert.match(textOf(n), /safety classifier/i);
  // command bar stays usable — no fields shown, but the toggles/footer still bind.
  assert.equal(vals.fields.length, 0);
});

test("truncation retry in progress → auto-retry banner", () => {
  const { vals } = render({ truncRetry: true, result: null });
  const n = notice(vals);
  assert.equal(n.props["data-notice-type"], "truncated");
  assert.match(textOf(n), /re-running with more headroom/i);
});

test("unknown_doc_type → blocking amber furniture, extraction halted, never defaults", () => {
  const { vals } = render({
    apiError: { type: "unknown_doc_type", message: "could not route" },
    routeBlocked: true,
  });
  assert.equal(vals.routeBlocked, true);
  assert.equal(vals.schemaToggleShadow, "inset 0 0 0 1px #E6CE9E"); // amber toggle
  assert.equal(vals.fields.length, 0); // blocked: nothing extracted yet
  assert.equal(vals.hasGhosts, false);
  const n = notice(vals);
  assert.match(textOf(n), /choose a schema/i);
});

test("choosing a schema while blocked clears the block and simulate, then re-extracts", () => {
  const calls = [];
  const { component } = loadComponent();
  component.api = { extract: (req) => { calls.push(req); return Promise.resolve({ ok: false, error: {} }); } };
  component.state = { sample: "pathology", mode: "live", simulate: "unknown_doc_type", routeBlocked: true, samples: [{ id: "path_report", text: "x" }], collapsed: [] };
  component.chooseSchema("intake");
  assert.equal(component.state.simulate, null);
  assert.equal(component.state.routeBlocked, false);
  assert.equal(component.state.sample, "intake");
  assert.equal(calls.length, 1); // re-extract issued
  assert.equal(calls[0].simulate, undefined); // without the simulate hook
});

// --- misroute hint ------------------------------------------------------------

test("mostly-not_found result → non-blocking misroute hint fires", () => {
  const result = JSON.parse(JSON.stringify(pathResult));
  result.fields.forEach((f) => {
    f.value = null;
    f.flag = "not_found";
    f.char_start = null;
    f.char_end = null;
  });
  const { vals } = render({ result });
  assert.equal(vals.misrouteHint, true);
  // a healthy result does not trip it
  const { vals: ok } = render({ result: pathResult });
  assert.equal(ok.misrouteHint, false);
});

// --- ListField group + collapse ----------------------------------------------

test("intake result → medications/allergies group headers; collapse hides items", () => {
  const { vals } = render({ sample: "intake", result: intakeResult });
  const meds = vals.listGroups.find((g) => g.name === "medications");
  assert.ok(meds, "medications group present");
  assert.match(meds.label, /medications · 3 of 3 grounded/);
  assert.equal(meds.expanded, true);
  // items present while expanded
  assert.ok(vals.fields.some((r) => r.name === "medications[0]"));

  // collapse medications → its items disappear from the rendered rows (counts unaffected).
  const { vals: collapsed } = render({
    sample: "intake",
    result: intakeResult,
    collapsed: ["medications"],
  });
  assert.ok(!collapsed.fields.some((r) => /^medications\[/.test(r.name)));
  // a non-collapsed scalar row (pcp) and allergies survive
  assert.ok(collapsed.fields.some((r) => r.name === "pcp"));
});

// --- offline chip / honesty furniture ----------------------------------------

test("stub mode → offline 'canned data' chip is shown", () => {
  const { vals } = render({ mode: "stub", result: null });
  assert.equal(vals.isOffline, true);
});

test("live mode → no offline chip", () => {
  const { vals } = render({ mode: "live", result: pathResult });
  assert.equal(vals.isOffline, false);
});

// --- truncation retry control flow (handleExtract) ---------------------------

test("handleExtract: a truncated envelope retries once without simulate (re-streams fresh)", () => {
  const { component } = loadComponent();
  const calls = [];
  component.api = {
    extract: (req) => {
      calls.push(req);
      return Promise.resolve({ doc_type: "pathology", fields: [], n_grounded: 0, n_null: 0, n_needs_review: 0 });
    },
  };
  component.state = { sample: "pathology", mode: "live", simulate: "truncated", result: null, collapsed: [] };
  // First response is a truncation envelope → the UI shows the retry banner and re-issues once.
  component.handleExtract({ ok: false, error: { type: "truncated" } }, {});
  assert.equal(component.state.truncRetry, true); // auto-retry banner up
  assert.equal(calls.length, 1); // exactly one retry issued
  assert.equal(calls[0].simulate, undefined); // ...without the simulate hook → it completes
});

test("handleExtract: a second truncation → final 'couldn't complete' notice, never a partial record", () => {
  const { component } = loadComponent();
  component.api = { extract: () => Promise.resolve({ ok: false, error: { type: "truncated" } }) };
  component.state = { sample: "pathology", mode: "live", simulate: "truncated", result: null, collapsed: [] };
  // the retry attempt itself truncates again
  component.handleExtract({ ok: false, error: { type: "truncated" } }, { retried: true });
  assert.equal(component.state.apiError.type, "truncated_final");
  assert.equal(component.state.result, null); // no partial record scored/shown
});
