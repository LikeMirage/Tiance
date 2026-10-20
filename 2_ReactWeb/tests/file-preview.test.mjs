import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const vite = await createServer({
  appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true },
});
after(() => vite.close());
const { needsPlainTextMode, previewPolicy } = await vite.ssrLoadModule("/src/features/file-preview/model/previewPolicy.ts");
const { previewEndpoint, readSpreadsheetPage } = await vite.ssrLoadModule("/src/features/file-preview/model/filePreview.ts");
const { pruneDocumentTextContentCache } = await vite.ssrLoadModule("/src/features/document-tabs/model/documentTextContentCache.ts");
const { resolveDocumentPreview } = await vite.ssrLoadModule("/src/features/document-tabs/model/documentPreviewResolver.ts");
const { checkedPreviewUrl, delimitedPreviewUrl } = await vite.ssrLoadModule("/src/features/file-preview/model/filePreview.ts");

test("CSV and TSV use paged assets and keep parsing options on every page request", () => {
  global.window = { location: { href: "http://localhost/app/" } };
  for (const name of ["报告.csv", "table.TSV"]) {
    assert.equal(resolveDocumentPreview({ name, kind: "file" }).kind, "office");
  }
  const src = delimitedPreviewUrl("http://localhost/api/projects/p/files/asset?path=folder%2Ffile.csv", "auto", "auto");
  const checked = checkedPreviewUrl(src, { version: "v1", delimited: { encoding: "gb18030", delimiter: "semicolon" } });
  const page = new URL(previewEndpoint(checked, "/spreadsheet"));
  assert.equal(page.searchParams.get("encoding"), "gb18030");
  assert.equal(page.searchParams.get("delimiter"), "semicolon");
  assert.equal(page.searchParams.get("path"), "folder/file.csv");
  delete global.window;
});

test("large text and exceptionally long lines switch mode without modifying source", () => {
  const content = "内容\n".repeat(previewPolicy.highlightedTextCharacters);
  assert.equal(needsPlainTextMode(content), true);
  assert.equal(needsPlainTextMode("x".repeat(10_001)), true);
  assert.equal(needsPlainTextMode("normal\n".repeat(10)), false);
  assert.equal(content.endsWith("内容\n"), true);
});

test("preview requests retain tool/project target, path and version across pagination", async () => {
  global.window = { location: { href: "http://localhost/app/" }, addEventListener() {} };
  global.document = { addEventListener() {} };
  const asset = "http://localhost/api/tools/categories/group/projects/tool/files/asset?path=a%2Fb.xlsx&v=4&preview_version=version";
  const endpoint = new URL(previewEndpoint(asset, "/spreadsheet"));
  assert.equal(endpoint.pathname, "/api/tools/categories/group/projects/tool/files/preview/spreadsheet");
  assert.equal(endpoint.searchParams.get("path"), "a/b.xlsx");
  assert.equal(endpoint.searchParams.has("preview_version"), false);
  const controller = new AbortController();
  const previousFetch = global.fetch;
  global.fetch = async (url, init) => {
    const request = new URL(url);
    assert.equal(request.searchParams.get("version"), "v1");
    assert.equal(request.searchParams.get("sheet"), "2");
    assert.equal(request.searchParams.get("row"), "50");
    assert.equal(request.searchParams.get("column"), "20");
    assert.equal(init.signal, controller.signal);
    return new Response(JSON.stringify({ version: "v2", values: [] }));
  };
  try {
    await assert.rejects(readSpreadsheetPage(asset, "v1", 2, 50, 20, controller.signal), /文件版本已变化/);
  } finally {
    global.fetch = previousFetch;
    delete global.window;
    delete global.document;
  }
});

test("preview cache eviction never discards unsaved editor content", () => {
  const dirty = { id: "dirty", kind: "text", content: "x".repeat(11_000_000), savedContent: "",
    textContentLoaded: true, isDirty: true, saveState: "idle", filePath: "source.txt" };
  const clean = { ...dirty, id: "clean", isDirty: false };
  const result = pruneDocumentTextContentCache([dirty, clean], null);
  assert.equal(result[0].content, dirty.content);
  assert.equal(result[1].textContentLoaded, false);
});

test("many small inactive files also obey the cache budget", () => {
  const tabs = Array.from({ length: 30 }, (_, i) => ({
    id: `file:${i}`, kind: "text", filePath: `${i}.txt`, content: "abc", savedContent: "abc",
    textContentLoaded: true, isDirty: false, saveState: "idle", textContentAccessedAt: i,
  }));
  const result = pruneDocumentTextContentCache(tabs, "file:0");
  assert.equal(result.filter((tab) => tab.textContentLoaded).length, 9); // active + 8 inactive
  assert.equal(result[0].content, "abc");
  assert.equal(result[1].textContentLoaded, false);
  assert.equal(result[29].content, "abc");
});
