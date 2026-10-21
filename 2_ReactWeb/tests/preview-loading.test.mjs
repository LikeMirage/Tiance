import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import React, { StrictMode } from "react";
import TestRenderer, { act } from "react-test-renderer";
import ts from "typescript";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const require = createRequire(import.meta.url);
function load(relative, mocks = {}) {
  const source = fs.readFileSync(new URL("../" + relative, import.meta.url), "utf8");
  const js = ts.transpileModule(source, { fileName: relative, compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const module = { exports: {} };
  vm.runInThisContext("(function(require,module,exports){" + js + "\n})", { filename: relative })(
    name => name in mocks ? mocks[name] : require(name), module, module.exports);
  return module.exports;
}
const context = load("src/shared/ui/loading-strip/loadingBoundaryContext.ts");
const { LoadingStrip } = load("src/shared/ui/loading-strip/LoadingStrip.tsx", {
  "./loadingBoundaryContext": context, "./loading-strip.css": {},
});
const { LoadingBoundary } = load("src/shared/ui/loading-strip/LoadingBoundary.tsx", {
  "./loadingBoundaryContext": context, "./LoadingStrip": { LoadingStrip },
});
const { EditorLazyBoundary } = load("src/features/document-editor-canvas/ui/EditorContentBoundary.tsx", {
  "../../../shared/ui/loading-strip": { LoadingStrip },
});
const rings = root => root.root.findAll(node => node.type === "div" && node.props.className?.includes("ds-loading-strip__ring-label"));
const surface = root => root.root.findByProps({ className: "ds-loading-boundary" });

test("one ring survives precheck, lazy import, and rendering; ready content is shown without timers", async () => {
  let resolveModule, finishRendering, mounts = 0;
  function Renderer() {
    const [pending, setPending] = React.useState(true);
    finishRendering = () => setPending(false);
    React.useLayoutEffect(() => { mounts++; }, []);
    return pending ? React.createElement(LoadingStrip, { visual: "ring" }) : React.createElement("output", null, "ready");
  }
  const LazyRenderer = React.lazy(() => new Promise(resolve => { resolveModule = resolve; }));
  const view = pending => React.createElement(LoadingBoundary, { pending }, pending ? null :
    React.createElement(EditorLazyBoundary, { resetKey: "document" }, React.createElement(LazyRenderer)));
  let root;
  await act(async () => { root = TestRenderer.create(view(true)); });
  const originalRing = rings(root)[0];
  assert.equal(rings(root).length, 1);
  await act(async () => root.update(view(false)));
  assert.equal(typeof resolveModule, "function"); // Import started immediately.
  assert.equal(rings(root)[0], originalRing);
  await act(async () => resolveModule({ default: Renderer }));
  assert.equal(mounts, 1);
  assert.equal(surface(root).props["aria-busy"], true);
  assert.equal(rings(root).length, 1);
  assert.equal(rings(root)[0], originalRing);
  await act(async () => finishRendering());
  assert.equal(rings(root).length, 0);
  assert.equal(surface(root).props["aria-busy"], false);
  assert.equal(root.root.findByType("output").children[0], "ready");
  assert.equal(root.root.findByProps({ className: "ds-loading-boundary__content" }).props.inert, false);
  await act(async () => root.unmount());
});

test("strict lifecycle and concurrent loaders release only after all initial work; later paging stays local", async () => {
  const view = (first, second) => React.createElement(StrictMode, null,
    React.createElement(LoadingBoundary, { pending: false },
      first ? React.createElement(LoadingStrip, { key: "first", visual: "ring" }) : null,
      second ? React.createElement(LoadingStrip, { key: "second", visual: "ring" }) : null,
      React.createElement("output", null, "document")));
  let root;
  await act(async () => { root = TestRenderer.create(view(true, true)); });
  assert.equal(rings(root).length, 1);
  await act(async () => root.update(view(false, true)));
  assert.equal(surface(root).props["aria-busy"], true);
  await act(async () => root.update(view(false, false)));
  assert.equal(surface(root).props["aria-busy"], false);
  assert.equal(rings(root).length, 0);
  await act(async () => root.update(view(true, false)));
  assert.equal(surface(root).props["aria-busy"], false);
  assert.equal(root.root.findAllByProps({ className: "ds-loading-boundary__overlay" }).length, 0);
  assert.equal(rings(root).length, 1);
  await act(async () => root.unmount());
});

test("replacing an in-flight child with an error removes its loading claim", async () => {
  const view = failed => React.createElement(LoadingBoundary, { pending: false },
    failed ? React.createElement("div", { role: "alert" }, "failed") : React.createElement(LoadingStrip));
  let root;
  await act(async () => { root = TestRenderer.create(view(false)); });
  assert.equal(surface(root).props["aria-busy"], true);
  await act(async () => root.update(view(true)));
  assert.equal(surface(root).props["aria-busy"], false);
  assert.equal(root.root.findByProps({ role: "alert" }).children[0], "failed");
  await act(async () => root.unmount());
});
