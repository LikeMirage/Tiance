import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement, useEffect } from "react";
import { act, create } from "react-test-renderer";
import { createServer } from "vite";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
after(() => vite.close());
const { SlidingContent } = await vite.ssrLoadModule("/src/shared/ui/sliding-content/SlidingContent.tsx");

function host({ reduced = false, height = 320 } = {}) {
  const animations = [];
  const observers = [];
  globalThis.window = { matchMedia: () => ({ matches: reduced }) };
  globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", borderTopWidth: "0", borderBottomWidth: "0" });
  globalThis.ResizeObserver = class {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe() {} disconnect() { this.disconnected = true; }
  };
  let active;
  const root = {
    style: {}, dataset: {},
    getBoundingClientRect() { return { height: active ? active.currentHeight : this.style.height === "auto" ? height : parseFloat(this.style.height) }; },
    animate(frames, options) {
      const animation = { frames, options, currentHeight: parseFloat(frames[0].height), cancelled: false,
        cancel() { this.cancelled = true; if (active === this) active = null; },
        finish() { if (active === this) active = null; this.onfinish?.(); } };
      active = animation; animations.push(animation); return animation;
    },
  };
  return {
    root, animations, observers,
    setHeight(next) { height = next; observers.filter((o) => !o.disconnected).forEach((o) => o.callback()); },
    createNodeMock(element) {
      if (element.props.className === "sliding-content__inner") return { getBoundingClientRect: () => ({ height }) };
      if (element.props.className?.startsWith("sliding-content ")) {
        if (!root.style.height) Object.assign(root.style, element.props.style);
        return root;
      }
      return {};
    },
  };
}

test("收起保留内容直到动画结束，随后卸载；展开不重复挂载", async () => {
  const environment = host();
  let mounted = 0, unmounted = 0, view;
  function Content() { useEffect(() => { mounted++; return () => unmounted++; }, []); return createElement("p", null, "思考正文"); }
  const render = (expanded) => createElement(SlidingContent, { expanded }, createElement(Content));
  try {
    await act(async () => { view = create(render(true), { createNodeMock: environment.createNodeMock }); });
    assert.equal(environment.animations.length, 0, "首次展示不播放入场动画");
    await act(async () => view.update(render(false)));
    assert.equal(unmounted, 0);
    assert.equal(view.root.findByType("p").children[0], "思考正文");
    assert.deepEqual(environment.animations[0].frames, [{ height: "320px" }, { height: "0px" }]);
    await act(async () => environment.animations[0].finish());
    assert.equal(unmounted, 1);
    assert.equal(view.root.findAllByType("p").length, 0);
    await act(async () => view.update(render(true)));
    await act(async () => environment.animations.at(-1).finish());
    assert.equal(mounted, 2);
    assert.equal(environment.root.style.height, "auto");
    await act(async () => environment.setHeight(800));
    assert.equal(environment.animations.length, 2, "流式增长不逐字触发高度动画");
  } finally { if (view) await act(async () => view.unmount()); }
});

test("快速反向切换从当前可见高度续接，旧动画不能卸载重新展开的内容", async () => {
  const environment = host();
  let view;
  const render = (expanded) => createElement(SlidingContent, { expanded }, createElement("p", null, "正文"));
  try {
    await act(async () => { view = create(render(true), { createNodeMock: environment.createNodeMock }); });
    await act(async () => view.update(render(false)));
    const old = environment.animations[0];
    const staleFinish = old.onfinish;
    old.currentHeight = 170;
    await act(async () => view.update(render(true)));
    assert.equal(old.cancelled, true);
    assert.equal(environment.animations[1].frames[0].height, "170px");
    await act(async () => staleFinish());
    assert.equal(view.root.findAllByType("p").length, 1);
    await act(async () => view.unmount()); view = null;
    assert.equal(environment.animations[1].cancelled, true);
    assert.ok(environment.observers.every((o) => o.disconnected));
  } finally { if (view) await act(async () => view.unmount()); }
});

test("长消息和代码收回预览高度，短内容不被撑高；减少动态效果立即结束", async () => {
  for (const reduced of [false, true]) {
    const environment = host({ reduced, height: 80 });
    let view;
    const render = (expanded) => createElement(SlidingContent, { expanded, collapsedHeight: 112 }, createElement("p", null, "正文"));
    try {
      await act(async () => { view = create(render(false), { createNodeMock: environment.createNodeMock }); });
      assert.equal(environment.root.style.height, "80px");
      await act(async () => environment.setHeight(600));
      assert.equal(environment.root.style.height, "112px");
      await act(async () => view.update(render(true)));
      if (!reduced) await act(async () => environment.animations.at(-1).finish());
      await act(async () => view.update(render(false)));
      if (!reduced) await act(async () => environment.animations.at(-1).finish());
      assert.equal(environment.root.style.height, "112px");
      assert.equal(view.root.findAllByType("p").length, 1);
      if (reduced) assert.equal(environment.animations.length, 0);
    } finally { if (view) await act(async () => view.unmount()); }
  }
});
