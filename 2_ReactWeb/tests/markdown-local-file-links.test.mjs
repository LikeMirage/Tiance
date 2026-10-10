import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";

const vite = await createServer({
  appType: "custom",
  logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)),
  server: { middlewareMode: true },
});
after(() => vite.close());
const { remarkLocalFilePaths } = await vite.ssrLoadModule(
  "/src/features/markdown-preview/model/remarkLocalFilePaths.ts",
);
const { resolveLocalFileReference } = await vite.ssrLoadModule(
  "/src/entities/local-file/model/localFileReference.ts",
);
const { resolveChatLocalFileTarget } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/chatLocalFileTarget.ts",
);
const { buildChatLocalFileNameIndex, createChatLocalFileNameAvailability } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/chatLocalFileNameIndex.ts",
);
const { MarkdownPreview } = await vite.ssrLoadModule(
  "/src/features/markdown-preview/ui/MarkdownPreview.tsx",
);
const { prepareMarkdownRender } = await vite.ssrLoadModule(
  "/src/features/markdown-preview/model/markdownRenderPipeline.ts",
);
const { buildStreamingMarkdownSegments, buildProgressiveMarkdownSegments } = await vite.ssrLoadModule(
  "/src/features/markdown-preview/model/markdownSegments.ts",
);

function references(markdown) {
  const result = [];
  renderToStaticMarkup(createElement(ReactMarkdown, {
    remarkPlugins: [remarkLocalFilePaths],
    urlTransform: (url) => url,
    components: {
      a({ href, children }) {
        result.push(resolveLocalFileReference(href, {
          projectId: "project",
          projectRootPath: "C:\\Projects\\current",
        }));
        return createElement("span", null, children);
      },
    },
  }, markdown));
  return result;
}

test("a file list following an explicit directory resolves outside the project", () => {
  const refs = references(
    "文件已保存至原图纸目录：\n\n`C:\\Users\\WW\\Desktop\\图纸\\`\n\n"
    + "- `NBFY3-01-01主动链轮.pdf`\n- `NBFY3-01-03主动轴.pdf`",
  );
  assert.equal(refs.length, 3);
  assert.deepEqual(refs.slice(1).map((ref) => [ref.absolutePath, ref.scope, ref.projectPath]), [
    ["C:\\Users\\WW\\Desktop\\图纸\\NBFY3-01-01主动链轮.pdf", "external", null],
    ["C:\\Users\\WW\\Desktop\\图纸\\NBFY3-01-03主动轴.pdf", "external", null],
  ]);
});

test("the directory applies only to the immediately following list", () => {
  const refs = references("`D:\\Export\\`\n\n- `a.pdf`\n\n项目文件：`readme.md`\n\n- `b.pdf`");
  assert.deepEqual(refs.map((ref) => ref.lookup === "name" ? ref.name : ref.absolutePath), [
    "D:\\Export", "D:\\Export\\a.pdf", "readme.md", "b.pdf",
  ]);
  assert.deepEqual(refs.slice(2).map((ref) => ref.absolutePath), [null, null]);
});

test("an intervening paragraph prevents directory inference", () => {
  const refs = references("`D:\\Export\\`\n\n其他工作区文件：\n\n- `a.pdf`");
  assert.equal(refs.at(-1).lookup, "name");
  assert.equal(refs.at(-1).name, "a.pdf");
});

test("absolute file paths and ordinary project links retain their own targets", () => {
  const refs = references("`D:\\Export\\`\n\n- `E:\\Other\\a.pdf`\n\n- [项目文件](docs/b.pdf)");
  assert.equal(refs[1].absolutePath, "E:\\Other\\a.pdf");
  assert.equal(refs[2].absolutePath, "C:\\Projects\\current\\docs\\b.pdf");
});

test("a directory needs an explicit trailing separator, including UNC paths", () => {
  const refs = references("`D:\\Export`\n\n- `a.pdf`\n\n`\\\\server\\share\\图纸\\`\n\n- `b.pdf`");
  assert.equal(refs[1].lookup, "name");
  assert.equal(refs[1].name, "a.pdf");
  assert.equal(refs[3].absolutePath, "\\\\server\\share\\图纸\\b.pdf");
});

test("streaming and progressive chunks keep the directory with its loose file list", () => {
  const source = "前文。\n\n`D:\\Export\\`\n\n- `a.pdf`\n\n- `b.pdf`\n\n";
  const streaming = buildStreamingMarkdownSegments(source, 10);
  const progressive = buildProgressiveMarkdownSegments(source, 10);
  for (const chunks of [
    [...streaming.chunks.map((chunk) => chunk.content), streaming.tail],
    progressive.map((chunk) => chunk.content),
  ]) {
    assert.equal(chunks.join(""), source);
    assert.deepEqual(chunks.flatMap(references).slice(1).map((ref) => ref.absolutePath), [
      "D:\\Export\\a.pdf", "D:\\Export\\b.pdf",
    ]);
  }
});

const context = { projectId: "project", projectRootPath: "C:\\Projects\\current" };
const snapshot = (paths, unreadable_paths = []) => ({
  project_id: "project", unreadable_paths,
  items: paths.map((path) => ({ name: path.split("/").at(-1), path, mtime_ms: 1 })),
});

test("正文先说目录再列裸文件名：全文和分段渲染都按真实文件打开", async () => {
  const source = "本次产出都在 `10月4日/` 目录下：\n\n**产出清单**\n\n"
    + "1. `10月4日_原始转写.txt`\n2. `10月4日_原文整理.md`\n3. `10月4日_会议纪要.docx`\n\n";
  const paths = ["10月4日/10月4日_原始转写.txt", "10月4日/10月4日_原文整理.md", "10月4日/10月4日_会议纪要.docx"];
  const streaming = buildStreamingMarkdownSegments(source, 10);
  for (const pieces of [[source], [...streaming.chunks.map((chunk) => chunk.content), streaming.tail],
    buildProgressiveMarkdownSegments(source, 10).map((chunk) => chunk.content)]) {
    const refs = pieces.flatMap(references).filter((ref) => ref.lookup === "name");
    const targets = await Promise.all(refs.map((ref) => resolveChatLocalFileTarget(ref, context, async () => snapshot(paths))));
    assert.deepEqual(targets.map((ref) => ref.projectPath), paths);
    assert.ok(targets.every((ref) => ref.absolutePath.startsWith("C:\\Projects\\current\\10月4日\\")));
  }
});

test("同名文件包括根目录的同名项也不会擅自选中", async () => {
  await assert.rejects(resolveChatLocalFileTarget(references("`报告.md`")[0], context,
    async () => snapshot(["报告.md", "归档/报告.md"])), (error) => {
      assert.match(error.message, /多个同名/);
      assert.match(error.message, /归档\/报告.md/);
      return true;
    });
});

test("带目录的路径和显式 ./ Markdown 链接不被替换成其他同名文件", async () => {
  const refs = references("`10月4日/报告.md` [根目录报告](./报告.md) `D:\\外部\\报告.md`");
  for (const ref of refs) {
    assert.strictEqual(await resolveChatLocalFileTarget(ref, context, async () => {
      throw new Error("不应搜索项目");
    }), ref);
  }
  assert.deepEqual(refs.map((ref) => ref.projectPath), ["10月4日/报告.md", "报告.md", null]);
});

test("未找到与搜索不完整会明确报错，不创建假路径", async () => {
  const ref = references("`报告.md`")[0];
  await assert.rejects(resolveChatLocalFileTarget(ref, context, async () => snapshot([])), /找不到文件/);
  await assert.rejects(resolveChatLocalFileTarget(ref, context, async () => snapshot(["报告.md"], ["受限目录"])), /不能确定文件名是否唯一/);
});

test("每次点击读取当前事实，文件移动、大小写和行号仍正确处理", async () => {
  const ref = references("`Report.md:17`")[0];
  assert.equal(ref.line, 17);
  for (const path of ["目录一/report.md", "目录二/report.md"]) {
    const resolved = await resolveChatLocalFileTarget(ref, context, async () => snapshot([path]));
    assert.equal(resolved.projectPath, path);
    assert.equal(resolved.line, 17);
  }
});

test("查找途中切换项目或关闭界面，中止请求且丢弃迟到结果", async () => {
  const controller = new AbortController();
  let complete;
  const pending = new Promise((resolve) => { complete = resolve; });
  const lookup = resolveChatLocalFileTarget(references("`报告.md`")[0], context, async (_id, init) => {
    assert.equal(init.signal, controller.signal);
    return pending;
  }, controller.signal);
  controller.abort();
  complete(snapshot(["目录/报告.md"]));
  await assert.rejects(lookup, { name: "AbortError" });
});

function renderFileLinks(content, paths, unreadable = [], currentContext = context) {
  const index = paths === null ? null : buildChatLocalFileNameIndex(snapshot(paths, unreadable), currentContext);
  return renderToStaticMarkup(createElement(MarkdownPreview, {
    content,
    resolveLocalFileReference: href => resolveLocalFileReference(href, currentContext),
    localFileActions: {
      fileNames: { getSnapshot: () => index, subscribe: () => () => {} },
      onOpenDefault() {}, onOpenInWorkspace() {}, onReveal() {}, onCopyPath() {},
    },
  }));
}

test("裸文件名只在工作区完整确认唯一文件后显示为链接，缺失/歧义/加载失败都是文字", () => {
  const content = "`报告.md` [同一裸文件名](报告.md) `三小网站_20261007.zip`";
  for (const html of [
    renderFileLinks(content, null), renderFileLinks(content, []),
    renderFileLinks(content, ["报告.md", "归档/报告.md"]),
    renderFileLinks(content, ["报告.md"], ["受限目录"]),
  ]) {
    assert.ok(!html.includes("<a"));
    assert.match(html, /三小网站_20261007\.zip/);
    assert.ok(!html.includes("tiance-local-path:"));
  }
  const html = renderFileLinks(content, ["资料/报告.md"]);
  assert.equal((html.match(/markdown-preview__local-file-link/g) ?? []).length, 2);
  assert.match(html, /title="C:\\Projects\\current\\资料\\报告.md"/);
  assert.match(html, /<span>三小网站_20261007\.zip<\/span>/);
});

test("裸文件名不扫描工作区外；完整路径不受文件名索引和同名歧义限制", () => {
  const content = "`报告.md` `C:\\Projects\\current\\报告.md` `D:\\下载\\报告.md` [指定根目录](./报告.md) [网页](https://example.com/report.md)";
  const html = renderFileLinks(content, ["报告.md", "归档/报告.md"]);
  assert.equal((html.match(/markdown-preview__local-file-link/g) ?? []).length, 3);
  assert.match(html, /<span>报告.md<\/span>/);
  assert.match(html, /title="D:\\下载\\报告.md"/);
  assert.match(html, /href="https:\/\/example.com\/report.md"/);
  assert.equal((renderFileLinks(content, null).match(/markdown-preview__local-file-link/g) ?? []).length, 3);
});

test("没有项目时裸文件名保持文字，完整外部路径仍可点击", () => {
  const html = renderFileLinks("`报告.md` [裸链接](报告.md) `D:\\下载\\报告.md`", null,
    [], { projectId: null, projectRootPath: "" });
  assert.equal((html.match(/markdown-preview__local-file-link/g) ?? []).length, 1);
  assert.match(html, /<span>报告.md<\/span>/);
  assert.match(html, /<span>裸链接<\/span>/);
  assert.ok(!html.includes('href="报告.md"'));
});

test("显式绝对 Markdown 路径和 file URI 在同步/后台渲染中都保留实际位置", () => {
  const content = "[外部文件](D:/Export/a.pdf) [项目文件](C:/Projects/current/docs/b.pdf) [文件URI](file:///D:/Export/c.pdf)";
  const refs = references(content);
  assert.deepEqual(refs.map(ref => [ref.absolutePath, ref.scope]), [
    ["D:\\Export\\a.pdf", "external"], ["C:\\Projects\\current\\docs\\b.pdf", "workspace"],
    ["D:\\Export\\c.pdf", "external"],
  ]);
  const html = renderFileLinks(content, null);
  assert.equal((html.match(/markdown-preview__local-file-link/g) ?? []).length, 3);
  const prepared = prepareMarkdownRender(content);
  assert.deepEqual(prepared.slots.map(slot => resolveLocalFileReference(slot.properties.href, context).absolutePath),
    refs.map(ref => ref.absolutePath));
});

function indexFixture(t) {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const requests = [];
  let handlers;
  let watches = 0, stops = 0;
  const files = createChatLocalFileNameAvailability(context, (_id, init) => new Promise((resolve, reject) => {
    requests.push({ resolve, reject, signal: init.signal });
  }), (_id, nextHandlers) => {
    handlers = nextHandlers; watches++;
    return () => { stops++; };
  });
  return { files, requests, get handlers() { return handlers; },
    get watches() { return watches; }, get stops() { return stops; } };
}
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };

test("整段历史的裸文件名共享一次扫描，未使用裸文件名时不扫描", async (t) => {
  const f = indexFixture(t);
  assert.equal(f.requests.length, 0);
  const stops = Array.from({ length: 100 }, () => f.files.subscribe(() => {}));
  assert.equal(f.requests.length, 1);
  assert.equal(f.watches, 1);
  f.requests[0].resolve(snapshot(["资料/Report.md"])); await flush();
  assert.equal(f.files.getSnapshot().get("report.md").projectPath, "资料/Report.md");
  stops.slice(0, 99).forEach(stop => stop());
  assert.equal(f.stops, 0);
  stops[99]();
  assert.equal(f.stops, 1);
  assert.equal(f.requests[0].signal.aborted, true);
});

test("文件变化合并刷新；新增、移动、同名与删除更新链接，纯内容修改不重渲染历史", async (t) => {
  const f = indexFixture(t);
  let changes = 0;
  const stop = f.files.subscribe(() => changes++); t.after(stop);
  f.requests[0].resolve(snapshot([])); await flush();
  for (const paths of [["a.md"], ["目录/a.md"], ["目录/a.md", "a.md"], []]) {
    for (let i = 0; i < 5; i++) f.handlers.onChanged(paths);
    const oldCount = f.requests.length;
    t.mock.timers.tick(200);
    assert.equal(f.requests.length, oldCount + 1);
    f.requests.at(-1).resolve(snapshot(paths)); await flush();
    assert.equal(f.files.getSnapshot().get("a.md")?.projectPath, paths.length === 1 ? paths[0] : undefined);
  }
  const before = changes;
  f.handlers.onChanged(["a.md"]); t.mock.timers.tick(200);
  f.requests.at(-1).resolve(snapshot([])); await flush();
  assert.equal(changes, before);
});

test("过期扫描、项目关闭、断线与扫描失败不能把未经确认的文件名变成链接", async (t) => {
  const f = indexFixture(t);
  let stop = f.files.subscribe(() => {});
  f.handlers.onChanged(["new.md"]);
  f.requests[0].resolve(snapshot(["old.md"])); await flush();
  assert.equal(f.files.getSnapshot(), null);
  t.mock.timers.tick(200);
  f.requests[1].resolve(snapshot(["new.md"])); await flush();
  assert.ok(f.files.getSnapshot().has("new.md"));
  f.handlers.onStatusChanged(false);
  assert.equal(f.files.getSnapshot(), null);
  f.handlers.onStatusChanged(true); t.mock.timers.tick(200);
  f.requests[2].reject(new Error("unavailable")); await flush();
  assert.equal(f.files.getSnapshot(), null);
  f.handlers.onOverflow(); t.mock.timers.tick(200);
  stop();
  assert.equal(f.requests[3].signal.aborted, true);
  stop = f.files.subscribe(() => {}); t.after(stop);
  f.requests[3].resolve(snapshot(["late.md"])); await flush();
  assert.equal(f.files.getSnapshot(), null);
  f.requests[4].resolve(snapshot(["current.md"])); await flush();
  assert.ok(f.files.getSnapshot().has("current.md"));
  assert.ok(!f.files.getSnapshot().has("late.md"));
});
