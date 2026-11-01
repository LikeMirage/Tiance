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
const { MarkdownPreview } = await vite.ssrLoadModule("/src/features/markdown-preview/ui/MarkdownPreview.tsx");
const { ContentReadinessContext, createContentReadiness } = await vite.ssrLoadModule("/src/shared/lib/contentReadiness.tsx");
const requests = [];
globalThis.Worker = class {
  postMessage(request) { requests.push({ ...request, worker: this }); }
  terminate() {}
};

function host() {
  let id = 0;
  const callbacks = new Map();
  const schedule = (callback) => { callbacks.set(++id, callback); return id; };
  const fragment = () => ({ querySelectorAll: () => [], cloneNode: fragment });
  globalThis.NodeFilter = { SHOW_COMMENT: 128 };
  globalThis.window = {
    requestAnimationFrame: schedule, cancelAnimationFrame: (id) => callbacks.delete(id),
    setTimeout: schedule, clearTimeout: (id) => callbacks.delete(id),
    document: {
      createTreeWalker(node) {
        let remaining = [...(node.anchors ?? [])];
        return { nextNode() { this.currentNode = remaining.shift(); return Boolean(this.currentNode); } };
      },
      createRange() { return { selectNode() {}, createContextualFragment: fragment }; },
    },
  };
  return {
    createNodeMock(element) {
      if (!element.props.dangerouslySetInnerHTML) return {};
      return { anchors: [{ data: "tiance-markdown-block:0", replaceWith() {} }], querySelectorAll: () => [] };
    },
    async drain() {
      while (callbacks.size) {
        const batch = [...callbacks.values()]; callbacks.clear();
        await act(async () => batch.forEach((callback) => callback()));
      }
    },
  };
}
function documentFor(text) {
  return { html: "<!--tiance-markdown-block:0-->", blocks: [`<p>${text}</p>`], slots: [], cacheWeight: 100 };
}
async function reply(request, document, error) {
  await act(async () => request.worker.onmessage({ data: { id: request.id, document, error } }));
}
function streamingNodes(view) {
  return view.root.findAll((node) => node.type === "div" && node.props.className?.includes("markdown-preview--streaming"));
}
function preparedNodes(view) {
  return view.root.findAll((node) => node.type === "div" && node.props.dangerouslySetInnerHTML);
}

test("流式正文一直保留到最终解析和分片 DOM 全部就绪，校准期间不出现空白", async () => {
  const environment = host();
  const readiness = createContentReadiness();
  const props = { content: "流式交接测试正文", renderStrategy: "responsive", isStreaming: true };
  const render = () => createElement(ContentReadinessContext.Provider, { value: readiness }, createElement(MarkdownPreview, props));
  let view;
  try {
    const count = requests.length;
    await act(async () => { view = create(render(), { createNodeMock: environment.createNodeMock }); });
    const streamedNode = streamingNodes(view)[0];
    assert.ok(streamedNode);
    assert.equal(requests.length, count, "流式阶段不重复启动全文 worker");
    props.isStreaming = false;
    await act(async () => view.update(render()));
    assert.equal(streamingNodes(view)[0], streamedNode, "结束事件不卸载已显示正文");
    assert.equal(view.root.findAll((node) => node.type === "div" && node.props.className?.includes("markdown-preview--responsive")).length,
      0, "等待完整解析时不能插入带 padding 的空预览容器");
    assert.equal(readiness.getSnapshot(), 0);
    await reply(requests.at(-1), documentFor(props.content));
    assert.equal(streamingNodes(view)[0], streamedNode, "解析完成后仍等待 DOM 挂载");
    assert.equal(preparedNodes(view)[0].props.style.display, "none", "准备内容不重复占用高度");
    assert.equal(readiness.getSnapshot(), 0);
    await environment.drain();
    assert.equal(streamingNodes(view).length, 0);
    assert.equal(preparedNodes(view)[0].props.style, undefined);
    assert.equal(preparedNodes(view)[0].props["aria-busy"], false);

    // A resumed response may settle with the same content, using a cached parse.
    props.isStreaming = true;
    await act(async () => view.update(render()));
    assert.equal(streamingNodes(view).length, 1);
    props.isStreaming = false;
    await act(async () => view.update(render()));
    assert.equal(streamingNodes(view).length, 1, "缓存命中也必须等新 DOM 就绪");
    await environment.drain();
    assert.equal(streamingNodes(view).length, 0);

    // Persisted content remains authoritative, even when it is shorter.
    props.content = "校准正文";
    await act(async () => view.update(render()));
    assert.deepEqual(streamingNodes(view)[0].findByType("p").children, ["校准正文"]);
    await reply(requests.at(-1), documentFor(props.content));
    await environment.drain();
    assert.equal(streamingNodes(view).length, 0);

    const settledContent = props.content;
    props.content = "尚未准备完成的修改";
    await act(async () => view.update(render()));
    props.content = settledContent;
    await act(async () => view.update(render()));
    assert.equal(streamingNodes(view).length, 1, "恢复缓存内容仍保留正文直至重新挂载完成");
    await environment.drain();
    assert.equal(streamingNodes(view).length, 0);
  } finally {
    if (view) await act(async () => view.unmount());
  }
});

test("最终排版失败时保留正文和重试入口；切走后迟到结果不污染新内容", async () => {
  const environment = host();
  let view;
  const props = { content: "保留出错前已显示的正文", renderStrategy: "responsive", isStreaming: true };
  try {
    await act(async () => { view = create(createElement(MarkdownPreview, props), { createNodeMock: environment.createNodeMock }); });
    props.isStreaming = false;
    await act(async () => view.update(createElement(MarkdownPreview, props)));
    await reply(requests.at(-1), undefined, "测试解析失败");
    assert.equal(streamingNodes(view).length, 1);
    assert.equal(view.root.findAllByProps({ role: "alert" }).length, 1);
    await act(async () => view.root.findByType("button").props.onClick());
    const old = requests.at(-1);
    props.content = "新的校准内容";
    await act(async () => view.update(createElement(MarkdownPreview, props)));
    await reply(old, documentFor("过时内容"));
    assert.equal(streamingNodes(view).length, 1);
    assert.equal(preparedNodes(view).length, 0);
    await reply(requests.at(-1), documentFor(props.content));
    await environment.drain();
    assert.equal(streamingNodes(view).length, 0);
  } finally {
    if (view) await act(async () => view.unmount());
  }
});
