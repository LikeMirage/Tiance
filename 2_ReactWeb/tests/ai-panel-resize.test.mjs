import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import React from "react";
import { act, create } from "react-test-renderer";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const vite = await createServer({
  appType: "custom",
  logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)),
  server: { middlewareMode: true },
});
const { useAiPanelLayout } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/useAiPanelLayout.ts",
);
after(() => vite.close());

test("restoring a narrow window keeps the editor visible and restores the preferred chat width", async () => {
  let containerWidth = 1500;
  let resizeObserver;
  const listeners = new Map();
  const commits = [];
  globalThis.window = {
    innerWidth: 2560,
    addEventListener(type, listener) { listeners.set(type, listener); },
    removeEventListener(type) { listeners.delete(type); },
  };
  globalThis.ResizeObserver = class {
    constructor(callback) { this.callback = callback; resizeObserver = this; }
    observe() {}
    disconnect() {}
  };

  let layout;
  function Harness() {
    layout = useAiPanelLayout({ initialWidth: 900, onWidthCommit: (width) => commits.push(width) });
    return React.createElement("div", { ref: layout.containerRef });
  }
  let renderer;
  try {
    await act(async () => {
      renderer = create(React.createElement(Harness), {
        createNodeMock: () => ({ getBoundingClientRect: () => ({ width: containerWidth }) }),
      });
    });
    assert.equal(layout.width, 900);

    await act(async () => {
      window.innerWidth = 1355;
      containerWidth = 769;
      listeners.get("resize")();
      resizeObserver.callback([{ contentRect: { width: containerWidth } }]);
    });
    assert.equal(layout.width, 488);
    assert.ok(containerWidth - layout.width >= 280);
    assert.deepEqual(commits, []);

    await act(async () => {
      window.innerWidth = 2560;
      containerWidth = 1500;
      resizeObserver.callback([{ contentRect: { width: containerWidth } }]);
    });
    assert.equal(layout.width, 900);
  } finally {
    if (renderer) await act(async () => renderer.unmount());
    delete globalThis.ResizeObserver;
    delete globalThis.window;
  }
});
