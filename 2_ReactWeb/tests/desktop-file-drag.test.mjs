import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
after(() => vite.close());
const drag = await vite.ssrLoadModule("/src/features/desktop-shell/model/desktopFileDrag.ts");
const composer = await vite.ssrLoadModule("/src/features/ai-panel/ui/chatComposerDrop.ts");
const mimeType = "application/x-tiance-project-file";
const reference = { projectId: "p", path: "会议记录.docx", name: "会议记录.docx", kind: "file" };
const data = { mimeType, data: JSON.stringify(reference) };
const paths = ["C:/项目/会议记录.docx"];
const settle = () => new Promise(resolve => setImmediate(resolve));

function environment(t) {
  const originals = Object.fromEntries(["window", "document", "navigator"].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  for (const [key, value] of Object.entries({ window: { pywebview: { api: {} } }, document: new EventTarget(), navigator: { platform: "Win32" } })) {
    Object.defineProperty(globalThis, key, { configurable: true, value });
  }
  t.after(() => {
    for (const [key, descriptor] of Object.entries(originals)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  });
  return window.pywebview.api;
}

test("native file drag leaves the clipboard alone and keeps the in-app project reference until drop", async t => {
  const api = environment(t);
  let complete, prevented = 0, unavailable = 0;
  const received = [];
  api.start_file_drag = value => { received.push(value); return new Promise(resolve => { complete = resolve; }); };
  api.set_clipboard_path_entries = () => assert.fail("Dragging must not replace the clipboard");
  assert.equal(drag.startDesktopFileDrag({ preventDefault: () => prevented++ }, paths, data, () => unavailable++), true);
  await settle();
  assert.deepEqual(received, [paths]);
  assert.equal(prevented, 1);
  assert.equal(drag.hasDesktopFileDragData(), true);
  const event = { dataTransfer: { types: ["Files"], getData: () => "" } };
  assert.equal(composer.hasDraggedProjectFile(event), true);
  const references = [];
  assert.equal(composer.handleChatComposerProjectFileDrop(event, { onDropProjectFile: value => references.push(value) }), true);
  assert.deepEqual(references, [reference]);
  document.dispatchEvent(new Event("drop"));
  assert.equal(drag.hasDesktopFileDragData(), false);
  complete(true);
  await settle();
  assert.equal(composer.hasDraggedProjectFile(event), false);
  assert.equal(unavailable, 0);
});

test("browser fallback, native cancellation and errors do not leave stale drag references", async t => {
  const api = environment(t);
  let prevented = 0, unavailable = 0;
  const event = { preventDefault: () => prevented++ };
  assert.equal(drag.startDesktopFileDrag(event, paths, data, () => unavailable++), false);
  assert.equal(prevented, 0);
  for (const start of [async () => true, async () => false, () => { throw new Error("bridge failed"); }]) {
    api.start_file_drag = start;
    assert.equal(drag.startDesktopFileDrag(event, paths, data, () => unavailable++), true);
    await settle();
    assert.equal(drag.hasDesktopFileDragData(), false);
  }
  assert.equal(unavailable, 2);
  assert.equal(composer.hasDraggedProjectFile({ dataTransfer: { types: [mimeType] } }), true);
});
