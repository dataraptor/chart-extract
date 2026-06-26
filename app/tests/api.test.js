/**
 * Split 07 — T1: `api.js` transport. Drives the client with an injected `fetch` (no network):
 * 2xx bodies pass through verbatim; a non-2xx error envelope resolves to a tagged
 * `{ok:false,error}` (never thrown); a dead server resolves to a `network` error — the signal the
 * component uses to fall back to offline-stub mode.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const Api = require("../api.js");

/** A canned fetch: records the last call, returns the configured response. */
function fakeFetch(response) {
  const calls = [];
  const fn = function (url, init) {
    calls.push({ url, init });
    return Promise.resolve(response);
  };
  fn.calls = calls;
  return fn;
}

function jsonRes(status, body) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

test("extract: posts JSON to /api/extract and returns the body verbatim", async () => {
  const result = { doc_type: "pathology", fields: [], n_grounded: 7 };
  const f = fakeFetch(jsonRes(200, result));
  const client = Api.makeClient({ fetch: f });
  const out = await client.extract({ sampleId: "path_report", schema: "pathology" });
  assert.deepEqual(out, result);
  assert.equal(f.calls[0].url, "/api/extract");
  assert.equal(f.calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(f.calls[0].init.body), {
    sample_id: "path_report",
    schema: "pathology",
  });
});

test("samples / evalReport / health: GET the right paths", async () => {
  const f = fakeFetch(jsonRes(200, []));
  const client = Api.makeClient({ fetch: f });
  await client.samples();
  await client.evalReport();
  await client.health();
  assert.deepEqual(f.calls.map((c) => c.url), ["/api/samples", "/api/eval", "/health"]);
});

test("error envelope: a non-2xx resolves to {ok:false,error}, never throws", async () => {
  const f = fakeFetch(
    jsonRes(409, { error: { type: "unknown_doc_type", message: "could not route", hint: "pick a schema" } })
  );
  const client = Api.makeClient({ fetch: f });
  const out = await client.extract({ text: "???" });
  assert.equal(out.ok, false);
  assert.equal(out.error.type, "unknown_doc_type");
  assert.equal(out.error.message, "could not route");
  assert.equal(out.error.hint, "pick a schema");
  assert.equal(out.status, 409);
});

test("dead server: a rejected fetch resolves to a network error (drives stub fallback)", async () => {
  const client = Api.makeClient({
    fetch: function () {
      return Promise.reject(new Error("ECONNREFUSED"));
    },
  });
  const out = await client.health();
  assert.equal(out.ok, false);
  assert.equal(out.error.type, "network");
});

test("non-JSON error body: still resolves to a tagged error", async () => {
  const f = fakeFetch({ ok: false, status: 500, json: () => Promise.reject(new Error("not json")) });
  const client = Api.makeClient({ fetch: f });
  const out = await client.health();
  assert.equal(out.ok, false);
  assert.match(out.error.message, /500/);
});
