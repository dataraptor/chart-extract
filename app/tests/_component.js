/**
 * Headless loader for the `Component` class inside `ChartExtract.dc.html` (Split 09 test support).
 *
 * No browser: it extracts the `<script type="text/x-dc">` class body and evaluates it against a
 * minimal shim of the bits the render path touches — a `DCLogic` base with a synchronous `setState`,
 * a `React.createElement` that returns inspectable descriptors, `window.ChartExtractMap`/`API`, and
 * stubs for `document`/`matchMedia`/`location`/timers. This lets the node test suite drive the real
 * `renderVals()` over the edge states and assert the view-model the DC template binds to — the same
 * "test independently" floor Split 07/08 used, extended to the failure states.
 */
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const HTML = path.join(__dirname, "..", "ChartExtract.dc.html");
const Map = require("../map.js");
const Api = require("../api.js");

/** A React.createElement shim: returns a descriptor tree we can search by data-testid / text. */
function makeReact() {
  function createElement(type, props, ...children) {
    const kids = children.length === 1 ? children[0] : children;
    return { $$el: true, type, props: props || {}, children: kids };
  }
  return { createElement, Fragment: "Fragment" };
}

/** Flatten a createElement descriptor tree to a list of nodes (for testid / text lookups). */
function walk(node, out) {
  out = out || [];
  if (node == null || node === false) return out;
  if (Array.isArray(node)) {
    node.forEach((n) => walk(n, out));
    return out;
  }
  if (node.$$el) {
    out.push(node);
    walk(node.children, out);
  }
  return out;
}

function textOf(node) {
  if (node == null || node === false) return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node.$$el) return textOf(node.children);
  return "";
}

function loadComponent(opts) {
  opts = opts || {};
  const html = fs.readFileSync(HTML, "utf8");
  const m = html.match(/data-dc-script[\s\S]*?>([\s\S]*?)<\/script>/);
  if (!m) throw new Error("component script not found");
  const body = m[1];

  const reduceMotion = !!opts.reduceMotion;
  const search = opts.search || "";

  const sandbox = {
    React: makeReact(),
    window: { ChartExtractMap: Map, ChartExtractAPI: opts.api || null },
    document: {
      getElementById: () => null,
      querySelectorAll: () => [],
    },
    matchMedia: (q) => ({ matches: reduceMotion && /reduced-motion/.test(q) }),
    location: { search },
    setInterval: () => 0,
    clearInterval: () => {},
    setTimeout: () => 0,
    console,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);

  // A minimal DCLogic base: synchronous setState (merge + functional updater + callback), props.
  const prelude = `
    class DCLogic {
      constructor(){ this.props = {}; }
      setState(updater, cb){
        const patch = (typeof updater === 'function') ? updater(this.state) : updater;
        if(patch) this.state = Object.assign({}, this.state, patch);
        if(cb) cb();
      }
    }
  `;
  const src = prelude + "\n" + body + "\nthis.__Component = Component;";
  vm.runInContext(src, sandbox);
  const Component = sandbox.__Component;

  const c = new Component();
  c.props = opts.props || {};
  c.api = sandbox.window.ChartExtractAPI;
  return { component: c, walk, textOf, walkAll: (vm2) => walk(vm2) };
}

module.exports = { loadComponent, walk, textOf };
