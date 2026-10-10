import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement, Fragment } from "react";
import { jsx, jsxs } from "react/jsx-runtime";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import ReactMarkdown from "react-markdown";
import { toJsxRuntime } from "hast-util-to-jsx-runtime";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";

const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
after(() => vite.close());
const { prepareMarkdownRender, parseMarkdownRenderTree } = await vite.ssrLoadModule("/src/features/markdown-preview/model/markdownRenderPipeline.ts");
const { normalizeMarkdownMath, markdownMathRemarkPlugins, markdownMathRehypePlugins } = await vite.ssrLoadModule("/src/features/markdown-preview/model/markdownMath.ts");
const { markdownHtmlSanitizeSchema } = await vite.ssrLoadModule("/src/features/markdown-preview/model/markdownHtmlSanitizeSchema.ts");
const { remarkLocalFilePaths } = await vite.ssrLoadModule("/src/features/markdown-preview/model/remarkLocalFilePaths.ts");
const { createMarkdownRenderClient } = await vite.ssrLoadModule("/src/features/markdown-preview/model/markdownRenderClient.ts");
const { createContentReadiness } = await vite.ssrLoadModule("/src/shared/lib/contentReadiness.tsx");
const { createMarkdownMountQueue } = await vite.ssrLoadModule("/src/features/markdown-preview/model/markdownMountQueue.ts");
const { getMarkdownDomBlock, rememberMarkdownDomBlock } = await vite.ssrLoadModule("/src/features/markdown-preview/model/markdownDomCache.ts");
const { MarkdownPreview } = await vite.ssrLoadModule("/src/features/markdown-preview/ui/MarkdownPreview.tsx");

function assembledHtml(document) {
  const expand = (html) => html.replace(/<!--tiance-markdown-block:(\d+)-->/g, (_, id) => expand(document.blocks[Number(id)]));
  return expand(document.html);
}

test("后台完整解析保持公式、表格、脚注、跨段引用和本地链接语义", () => {
  const source = [
    "# 数学内容", "",
    String.raw`$$\sum_{i=1}^{n}\frac{x_i}{1+\sqrt{i}}$$`, "",
    String.raw`化学 $\ce{H2O}$ 和行内 $x^2$。`, "",
    "| 项目 | 公式 |", "| --- | --- |", "| A | $x+y$ |", "",
    "正文 [参考][target] 与脚注[^n]。`报告.md`", "",
    "[target]: https://example.com", "[^n]: 脚注正文", "",
    "<details><summary>更多</summary>内容</details>",
  ].join("\n");
  const expected = renderToStaticMarkup(createElement(ReactMarkdown, {
    remarkPlugins: [remarkGfm, remarkLocalFilePaths, ...markdownMathRemarkPlugins],
    rehypePlugins: [rehypeRaw, [rehypeSanitize, markdownHtmlSanitizeSchema], ...markdownMathRehypePlugins],
    urlTransform: (url) => url,
  }, normalizeMarkdownMath(source)));
  const actual = renderToStaticMarkup(toJsxRuntime(parseMarkdownRenderTree(source), {
    Fragment, jsx, jsxs, passNode: true, passKeys: true, ignoreInvalidStyle: true,
  }));
  assert.equal(actual, expected);
});

test("后台完整生成表格和公式，隐藏 DOM 准备保留完整结构", () => {
  const source = Array.from({ length: 150 }, (_, i) => `| ${i} | $\\frac{x_i}{1+\\sqrt{i}}$ |`).join("\n");
  const document = prepareMarkdownRender(`| 编号 | 公式 |\n| --- | --- |\n${source}`);
  const html = assembledHtml(document);
  assert.equal((html.match(/<tr>/g) ?? []).length, 151);
  assert.equal((html.match(/class="katex"/g) ?? []).length, 150);
  assert.equal(document.slots.length, 0);
  assert.ok(!document.html.includes("tiance-render-chunk"));
  const formulas = prepareMarkdownRender((String.raw`$$\frac{x}{y}$$` + "\n\n").repeat(400) + "完整内容终点");
  assert.equal((assembledHtml(formulas).match(/class="katex"/g) ?? []).length, 400);
  assert.match(assembledHtml(formulas), /完整内容终点/);
});

test("表格内嵌显示公式的兜底排版也在分片前完成，保留公式错误提示", () => {
  const source = String.raw`<table><tbody><tr><td>前 \[\frac{x}{y}\] 后</td><td>\[\invalidcommand\]</td></tr></tbody></table>`;
  const expected = renderToStaticMarkup(createElement(MarkdownPreview, { content: source }));
  const actual = assembledHtml(prepareMarkdownRender(source));
  for (const html of [expected, actual]) {
    assert.equal((html.match(/class="katex"/g) ?? []).length, 2);
    assert.match(html, /markdown-preview__table-cell-math--display/);
    assert.match(html, /data-math-render-error="true"/);
    assert.match(html, /前 /);
    assert.match(html, / 后/);
  }
});

test("等待统一消息区加载时不显示逐条动画，代码交互仍保持原始节点且 HTML 被清理", () => {
  const source = "```js\nconst a = '$x$';\n```\n\n<script>bad()</script><img src='x' onerror='bad()'>\n\n[bad](javascript:bad())";
  const document = prepareMarkdownRender(source);
  const pre = document.slots.find((node) => node.tagName === "pre");
  assert.equal(pre.children[0].tagName, "code");
  assert.equal(pre.children[0].children[0].value, "const a = '$x$';\n");
  const serialized = JSON.stringify(document);
  assert.ok(!serialized.includes('"tagName":"script"'));
  assert.ok(!serialized.includes("onerror"));
  assert.ok(!serialized.includes("javascript:"));
  const html = renderToStaticMarkup(createElement(MarkdownPreview, { content: source, renderStrategy: "responsive" }));
  assert.ok(!html.includes("正在加载"));
  assert.match(html, /aria-busy="true"/);
  assert.ok(!html.includes("const a"));
});

test("切走时终止正在解析的旧内容，迟到结果不能覆盖新会话", async () => {
  const workers = [];
  const client = createMarkdownRenderClient(() => {
    const worker = { sent: [], terminated: false, postMessage(value) { this.sent.push(value); },
      terminate() { this.terminated = true; } };
    workers.push(worker);
    return worker;
  });
  const old = client.request("长会话");
  const rejected = assert.rejects(old.promise, { name: "AbortError" });
  const next = client.request("新会话");
  const staleCallback = workers[0].onmessage;
  old.cancel();
  await rejected;
  assert.equal(workers[0].terminated, true);
  assert.equal(workers[1].sent[0].content, "新会话");
  staleCallback({ data: { id: 1, document: { old: true } } });
  workers[1].onmessage({ data: { id: 2, document: { next: true } } });
  assert.deepEqual(await next.promise, { next: true });
});

test("重新挂载历史直接复用结果，同内容只解析一次，单个视图切走不取消其他视图", async () => {
  const workers = [];
  const client = createMarkdownRenderClient(() => {
    const worker = { sent: [], terminated: false, postMessage(value) { this.sent.push(value); }, terminate() { this.terminated = true; } };
    workers.push(worker);
    return worker;
  });
  const first = client.request("历史正文");
  const second = client.request("历史正文");
  const cancelled = assert.rejects(first.promise, { name: "AbortError" });
  first.cancel();
  await cancelled;
  assert.equal(workers[0].terminated, false);
  assert.equal(workers[0].sent.length, 1);
  const document = { html: "完整历史正文", blocks: [], slots: [], cacheWeight: 12 };
  workers[0].onmessage({ data: { id: 1, document } });
  assert.equal(await second.promise, document);
  assert.equal(client.getCached("历史正文"), document);
  assert.equal(await client.request("历史正文").promise, document);
  assert.equal(workers[0].sent.length, 1);
});

test("同一次界面更新卸载又挂载正文时复用在途解析，不反复重建 worker", async () => {
  const workers = [];
  const client = createMarkdownRenderClient(() => {
    const worker = { sent: [], terminated: false, postMessage(value) { this.sent.push(value); }, terminate() { this.terminated = true; } };
    workers.push(worker);
    return worker;
  });
  let request = client.request("含大量公式的历史");
  for (let index = 0; index < 50; index += 1) {
    const rejected = assert.rejects(request.promise, { name: "AbortError" });
    request.cancel();
    request = client.request("含大量公式的历史");
    await rejected;
  }
  assert.equal(workers.length, 1);
  assert.equal(workers[0].terminated, false);
  assert.equal(workers[0].sent.length, 1);
  const document = { html: "完整内容", blocks: [], slots: [], cacheWeight: 12 };
  workers[0].onmessage({ data: { id: 1, document } });
  assert.equal(await request.promise, document);
});

test("渲染缓存有大小上限，逐出旧会话不影响在用结果", async () => {
  let callback;
  const client = createMarkdownRenderClient(() => ({ postMessage({id}) {
    queueMicrotask(() => callback({data:{id, document:{html:String(id),slots:[],cacheWeight:7}}}));
  }, terminate() {}, set onmessage(value) { callback = value; } }), 10);
  const old = await client.request("旧会话").promise;
  await client.request("新会话").promise;
  assert.equal(client.getCached("旧会话"), undefined);
  assert.equal(old.html, "1");
  assert.equal(client.getCached("新会话").html, "2");
});

test("统一加载状态等待所有内容，卸载与重复结束都不会遗留任务", () => {
  const readiness = createContentReadiness();
  const first = readiness.begin();
  const second = readiness.begin();
  assert.equal(readiness.getSnapshot(), 2);
  first();
  first();
  assert.equal(readiness.getSnapshot(), 1);
  second();
  assert.equal(readiness.getSnapshot(), 0);
});

test("隐藏 DOM 准备按时间预算批量处理，超过预算才让出绘制，切走取消后续工作", () => {
  let frame, timer, now = 0;
  const queue = createMarkdownMountQueue({ requestFrame(callback) { frame = callback; return 1; }, cancelFrame() {frame=null;},
    setTimer(callback) {timer=callback;return 2;},clearTimer(){timer=null;},now(){return now;} });
  const done = [];
  queue(()=>{done.push(1);now+=3;});
  queue(()=>{done.push(2);now+=3;});
  queue(()=>{done.push(3);now+=3;});
  const cancel = queue(()=>done.push(4));
  const paint = frame; frame=null;paint();
  const work = timer;timer=null;work();
  assert.deepEqual(done,[1,2,3]);
  cancel();
  assert.equal(frame,null);
  assert.equal(timer,null);
});

test("DOM 缓存保留独立小块并限制内存，逐出不改变正在使用的模板", () => {
  const fragment = (nodes) => ({ querySelectorAll() { return { length: nodes }; }, cloneNode() { return fragment(nodes); } });
  const oldDocument = { cacheWeight: 100 };
  const nextDocument = { cacheWeight: 100 };
  const source = fragment(70_000);
  rememberMarkdownDomBlock(oldDocument, 0, source);
  const cached = getMarkdownDomBlock(oldDocument, 0);
  assert.notEqual(cached, source);
  assert.equal(getMarkdownDomBlock(oldDocument, 1), undefined);
  rememberMarkdownDomBlock(nextDocument, 0, fragment(40_000));
  assert.equal(getMarkdownDomBlock(oldDocument, 0), undefined);
  assert.equal(cached.querySelectorAll("*").length, 70_000);
  assert.ok(getMarkdownDomBlock(nextDocument, 0));
  const oversized = { cacheWeight: 8_000_001 };
  rememberMarkdownDomBlock(oversized, 0, fragment(1));
  assert.equal(getMarkdownDomBlock(oversized, 0), undefined);
  const documents = Array.from({ length: 17 }, () => ({ cacheWeight: 1 }));
  documents.forEach((document) => rememberMarkdownDomBlock(document, 0, fragment(1)));
  assert.equal(getMarkdownDomBlock(documents[0], 0), undefined);
  assert.ok(getMarkdownDomBlock(documents[16], 0));
});
