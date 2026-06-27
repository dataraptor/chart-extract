/**
 * ChartExtract API client (Split 07) — a thin transport over the Split 06 HTTP routes.
 *
 * No business logic: just `fetch` over the same-origin `/api/*` endpoints plus parsing of the
 * structured error envelope (`{error:{type,message,hint}}`). A non-2xx (or a dead server) resolves
 * to a tagged `{ ok:false, error }` object — it never throws — so the component renders a calm
 * notice instead of a blank screen (the full per-type notices are Split 09). A 2xx resolves to the
 * parsed body verbatim (e.g. `POST /api/extract` → the raw `ExtractionResult`), so nothing is
 * recomputed in the client.
 *
 * Pure and dependency-free: it runs in the browser (as `window.ChartExtractAPI`) and under Node's
 * test runner (as a CommonJS module).
 */
(function (root, factory) {
  var mod = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = mod; // Node/tests: { makeClient, errorResult, networkError }
  } else {
    // Browser: a ready same-origin client (the four methods the component calls), with the
    // factory helpers attached for completeness.
    var client = mod.makeClient();
    client.makeClient = mod.makeClient;
    client.errorResult = mod.errorResult;
    client.networkError = mod.networkError;
    root.ChartExtractAPI = client;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  /** A tagged error result the UI checks with `r && r.ok === false` (never thrown). */
  function errorResult(type, message, hint, status) {
    return { ok: false, error: { type: type, message: message, hint: hint || null }, status: status || 0 };
  }

  /** The network-unreachable envelope — drives the offline-stub fallback (§4). */
  function networkError() {
    return errorResult(
      "network",
      "Cannot reach the ChartExtract API — is the server running?",
      "start it with `chartextract-api`",
      0
    );
  }

  /**
   * Construct a client.
   * @param {{baseUrl?: string, fetch?: Function}} [opts] — same-origin (`""`) by default;
   *   `fetch` is injectable so the test suite drives canned responses with no network.
   */
  function makeClient(opts) {
    opts = opts || {};
    var baseUrl = opts.baseUrl != null ? opts.baseUrl : "";
    var fetchImpl = opts.fetch || (typeof fetch !== "undefined" ? fetch : null);

    function request(path, init) {
      if (!fetchImpl) {
        return Promise.resolve(networkError());
      }
      return fetchImpl(baseUrl + path, init).then(
        function (res) {
          return res.json().then(
            function (body) {
              return finish(res, body);
            },
            function () {
              return finish(res, null);
            }
          );
        },
        function () {
          return networkError();
        }
      );
    }

    function finish(res, body) {
      if (!res.ok) {
        var env = body && body.error ? body.error : {};
        return errorResult(
          env.type || "error",
          env.message || "request failed (" + res.status + ")",
          env.hint || null,
          res.status
        );
      }
      return body;
    }

    function getJson(path) {
      return request(path, { method: "GET" });
    }

    return {
      /** GET /api/samples → Sample[] (or `{ok:false,error}`). */
      samples: function () {
        return getJson("/api/samples");
      },
      /**
       * POST /api/extract → ExtractionResult (or `{ok:false,error}`).
       * @param {{sampleId?:string, text?:string, schema?:string, provider?:string,
       *          simulate?:string}} req — `simulate` drives the dev-only edge-state hook
       *   (Split 09); it's appended as a query param and is inert unless the server is in dev mode.
       */
      extract: function (req) {
        req = req || {};
        var payload = {};
        if (req.sampleId != null) payload.sample_id = req.sampleId;
        if (req.text != null) payload.text = req.text;
        if (req.schema != null) payload.schema = req.schema;
        if (req.provider != null) payload.provider = req.provider;
        var path = "/api/extract";
        if (req.simulate) path += "?simulate=" + encodeURIComponent(req.simulate);
        return request(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      },
      /**
       * POST /api/extract (multipart) → ExtractionResult (or `{ok:false,error}`). Wires the upload
       * drop-zone; an unsupported file resolves to the `415 unsupported_file` envelope (never throws).
       * @param {File|Blob} file
       * @param {{schema?:string, provider?:string}} [opts]
       */
      extractFile: function (file, opts) {
        opts = opts || {};
        var fd = new FormData();
        fd.append("file", file, file && file.name ? file.name : "upload");
        if (opts.schema != null) fd.append("schema", opts.schema);
        if (opts.provider != null) fd.append("provider", opts.provider);
        return request("/api/extract", { method: "POST", body: fd });
      },
      /** GET /api/eval → EvalReport (or `{ok:false,error}`). */
      evalReport: function () {
        return getJson("/api/eval");
      },
      /** GET /health → {status, provider, model} (or `{ok:false,error}` when unreachable). */
      health: function () {
        return getJson("/health");
      },
    };
  }

  return { makeClient: makeClient, errorResult: errorResult, networkError: networkError };
});
