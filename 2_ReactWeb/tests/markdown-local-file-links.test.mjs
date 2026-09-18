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
  assert.deepEqual(refs.map((ref) => ref.absolutePath), [
    "D:\\Export", "D:\\Export\\a.pdf", "C:\\Projects\\current\\readme.md", "C:\\Projects\\current\\b.pdf",
  ]);
});

test("an intervening paragraph prevents directory inference", () => {
  const refs = references("`D:\\Export\\`\n\n其他工作区文件：\n\n- `a.pdf`");
  assert.equal(refs.at(-1).absolutePath, "C:\\Projects\\current\\a.pdf");
});

test("absolute file paths and ordinary project links retain their own targets", () => {
  const refs = references("`D:\\Export\\`\n\n- `E:\\Other\\a.pdf`\n\n- [项目文件](docs/b.pdf)");
  assert.equal(refs[1].absolutePath, "E:\\Other\\a.pdf");
  assert.equal(refs[2].absolutePath, "C:\\Projects\\current\\docs\\b.pdf");
});

test("a directory needs an explicit trailing separator, including UNC paths", () => {
  const refs = references("`D:\\Export`\n\n- `a.pdf`\n\n`\\\\server\\share\\图纸\\`\n\n- `b.pdf`");
  assert.equal(refs[1].absolutePath, "C:\\Projects\\current\\a.pdf");
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
