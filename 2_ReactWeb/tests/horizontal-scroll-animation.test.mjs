import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { createServer } from "vite";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
after(() => vite.close());
const { useHorizontalScrollAnimation } = await vite.ssrLoadModule(
  "/src/shared/model/horizontal-scroll-animation/useHorizontalScrollAnimation.ts",
);

for (const reduced of [false, true]) {
  test(`横向滚动平滑到达目标，允许程序主动跳转和取消；系统减少动画=${reduced}`, async () => {
    const frames = new Map();
    let serial = 0, now = 0, hook, view;
    globalThis.window = {
      matchMedia: () => ({ matches: reduced }),
      performance: { now: () => now },
      requestAnimationFrame(fn) { frames.set(++serial, fn); return serial; },
      cancelAnimationFrame(id) { frames.delete(id); },
    };
    const tick = (elapsed) => {
      now += elapsed;
      const pending = [...frames.values()];
      frames.clear();
      pending.forEach((fn) => fn(now));
    };
    function Harness() { hook = useHorizontalScrollAnimation(); return null; }
    const element = { scrollLeft: 0, scrollWidth: 1000, clientWidth: 200 };
    try {
      await act(async () => { view = create(createElement(Harness)); });
      hook.scrollHorizontallyTo(element, 600);
      assert.equal(element.scrollLeft, 0);
      tick(60);
      assert.ok(element.scrollLeft > 0 && element.scrollLeft < 600);
      tick(180);
      assert.equal(element.scrollLeft, 600);
      assert.equal(frames.size, 0);

      hook.scrollHorizontallyTo(element, 0);
      tick(60);
      const interrupted = element.scrollLeft;
      hook.cancelHorizontalScroll();
      tick(500);
      assert.equal(element.scrollLeft, interrupted);
      assert.equal(frames.size, 0);

      hook.scrollHorizontallyTo(element, 2000, { animate: false });
      assert.equal(element.scrollLeft, 800, "显式跳转仍直接到达合法边界");
      assert.equal(frames.size, 0);
      hook.scrollHorizontallyTo(element, 0);
      await act(async () => view.unmount()); view = null;
      assert.equal(frames.size, 0, "卸载清理未完成的动画");
    } finally { if (view) await act(async () => view.unmount()); }
  });
}
