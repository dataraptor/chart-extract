/**
 * ExtractionResult → component view-model mapper (Split 07) — the load-bearing, unit-tested piece.
 *
 * A pure function family that turns the Split 06 API JSON into exactly the shapes the existing
 * `Component` in `ChartExtract.dc.html` already consumes — so the render code barely changes. It
 * maps the data source; it never rebuilds the UI and it never re-derives offsets or flags. In live
 * mode the engine is the source of truth: `toFieldRows`/`toHighlightRanges` carry
 * `char_start`/`char_end`/`match_quality`/`flag`/`confidence` straight from the result. The JS
 * `ground()/grounded()` in the component stay only as the offline-stub fallback and the parity
 * reference — they are NOT called in live mode.
 *
 * Dependency-free: runs in the browser (as `window.ChartExtractMap`) and under Node's test runner.
 */
(function (root, factory) {
  var mod = factory();
  if (typeof module === "object" && module.exports) module.exports = mod;
  else root.ChartExtractMap = mod;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // ---- small helpers -------------------------------------------------------

  function fields(result) {
    return (result && Array.isArray(result.fields) && result.fields) || [];
  }

  function countFlag(result, flag) {
    return fields(result).filter(function (f) {
      return f.flag === flag;
    }).length;
  }

  /** `$0.011` — 3 decimals, matching the existing cost chip. */
  function fmtCost(usd) {
    return "$" + Number(usd || 0).toFixed(3);
  }

  /** `3.4s` — 1 decimal, matching the existing latency chip. */
  function fmtLatency(s) {
    return Number(s || 0).toFixed(1) + "s";
  }

  /** A hallucination rate of exactly 0 reads as the bare `0` headline; otherwise 2 decimals. */
  function fmtRate(rate) {
    var n = Number(rate || 0);
    return n === 0 ? "0" : n.toFixed(2);
  }

  function pct(x) {
    return Math.round(Number(x || 0) * 100) + "%";
  }

  // ---- field rows ----------------------------------------------------------

  /**
   * `result.fields[]` → the rows the component's render loop expects, in the SAME shape the JS
   * `grounded()` returns (so `renderVals()` consumes them unchanged): the engine's `null` flag
   * (accepted) becomes the literal `'accepted'` the `FLAGS` table keys on, offsets are carried
   * verbatim as `s`/`e`, and `model_value` rides along as `proposed` for the "what the model said"
   * disclosure on a caught hallucination (`not_grounded`).
   */
  function toFieldRows(result) {
    return fields(result).map(function (f) {
      return {
        name: f.name,
        value: f.value === undefined ? null : f.value,
        flag: f.flag || "accepted",
        conf: f.confidence || 0,
        span: f.source_span || "",
        // offsets straight from the engine — NEVER recomputed in JS.
        s: f.char_start === undefined ? null : f.char_start,
        e: f.char_end === undefined ? null : f.char_end,
        q: f.match_quality || "none",
        // the rejected proposal the engine retained (only set on not_grounded).
        proposed: f.model_value === undefined ? null : f.model_value,
        model_value: f.model_value === undefined ? null : f.model_value,
      };
    });
  }

  // ---- document-pane highlight ranges --------------------------------------

  /**
   * Build the highlight ranges directly from the API `char_start`/`char_end`/`flag` — only fields
   * the engine actually located (non-null offsets). The component layers the active/pinned filter
   * and the flag→color on top; the *positions* come from here and are never re-derived by the JS
   * `ground()`.
   */
  function toHighlightRanges(result) {
    return fields(result)
      .filter(function (f) {
        return f.char_start != null && f.char_end != null;
      })
      .map(function (f) {
        return {
          name: f.name,
          s: f.char_start,
          e: f.char_end,
          flag: f.flag || "accepted",
        };
      });
  }

  // ---- footer counts / meta ------------------------------------------------

  /** The footer's "N grounded · M null (… ) · K review" line + the cost/latency/version chips. */
  function toFooterCounts(result) {
    result = result || {};
    var nF = countFlag(result, "not_found");
    var nA = countFlag(result, "not_assessed");
    var nG = countFlag(result, "not_grounded");
    var grounded = result.n_grounded || 0;
    var nulls = result.n_null || 0;
    var review = result.n_needs_review || 0;
    var countsText =
      grounded +
      " grounded · " +
      nulls +
      " null (" +
      nF +
      " not_found · " +
      nA +
      " not_assessed" +
      (nG ? " · " + nG + " not_grounded" : "") +
      ")" +
      (review ? " · " + review + " review" : "");
    return {
      countsText: countsText,
      cost: fmtCost(result.cost_usd),
      latency: fmtLatency(result.latency_s),
      pv: "prompt " + (result.prompt_version || ""),
      sv: "schema " + (result.schema_version || ""),
      model: result.model || "",
    };
  }

  // ---- JSON inspector ------------------------------------------------------

  /** The JSON-inspector body = the raw `ExtractionResult` (real offsets the buyer verifies). */
  function toJsonText(result) {
    return JSON.stringify(result || {}, null, 2);
  }

  // ---- eval leaderboard ----------------------------------------------------

  /** `EvalSummary` (/api/eval) → the exact strings the existing leaderboard markup binds to. */
  function toEvalView(report) {
    report = report || {};
    var rows = (report.rows || []).map(function (r) {
      return {
        name: r.name,
        p: Number(r.p || 0).toFixed(2),
        r: Number(r.r || 0).toFixed(2),
        f1: Number(r.f1 || 0).toFixed(2),
        w: pct(r.f1),
        note: r.note || "",
      };
    });
    var cost = (report.cost || []).map(function (c) {
      return {
        model: c.model,
        f1: Number(c.f1 || 0).toFixed(2),
        usd: fmtCost(c.usd_per_doc) + "/doc",
        delta: c.delta != null ? Math.round(c.delta) + "%" : null,
      };
    });
    return {
      macroF1: Number(report.macro_f1 || 0).toFixed(2),
      halluc: fmtRate(report.hallucination_rate),
      routing: Number(report.routing_accuracy || 0).toFixed(2),
      goldCount: report.gold_count || 0,
      evalRows: rows,
      cost: cost,
    };
  }

  return {
    toFieldRows: toFieldRows,
    toHighlightRanges: toHighlightRanges,
    toFooterCounts: toFooterCounts,
    toJsonText: toJsonText,
    toEvalView: toEvalView,
  };
});
