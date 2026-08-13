import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const vite = await createServer({
  appType: "custom",
  logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)),
  server: { middlewareMode: true },
});
const {
  isAutomaticSoftwareUpdateCheckEnabled,
  setAutomaticSoftwareUpdateCheckEnabled,
} = await vite.ssrLoadModule(
  "/src/features/software-update/model/softwareUpdatePreferences.ts",
);

let originalWindow;

before(() => {
  originalWindow = globalThis.window;
});

after(async () => {
  globalThis.window = originalWindow;
  await vite.close();
});

test("启动更新检查默认开启并保存用户选择", () => {
  const values = new Map();
  globalThis.window = {
    localStorage: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
    },
  };

  assert.equal(isAutomaticSoftwareUpdateCheckEnabled(), true);
  setAutomaticSoftwareUpdateCheckEnabled(false);
  assert.equal(isAutomaticSoftwareUpdateCheckEnabled(), false);
  setAutomaticSoftwareUpdateCheckEnabled(true);
  assert.equal(isAutomaticSoftwareUpdateCheckEnabled(), true);
});

test("浏览器存储不可用时保持默认开启且不阻断启动", () => {
  globalThis.window = {
    localStorage: {
      getItem: () => { throw new Error("blocked"); },
      setItem: () => { throw new Error("blocked"); },
    },
  };

  assert.equal(isAutomaticSoftwareUpdateCheckEnabled(), true);
  assert.doesNotThrow(() => setAutomaticSoftwareUpdateCheckEnabled(false));
});

test("更新面板和启动弹窗使用安全 Markdown 预览渲染版本说明", async () => {
  const panelSource = await readFile(
    new URL("../src/features/software-update/ui/SoftwareUpdatePanel.tsx", import.meta.url),
    "utf8",
  );
  const promptSource = await readFile(
    new URL("../src/features/software-update/ui/StartupSoftwareUpdatePrompt.tsx", import.meta.url),
    "utf8",
  );

  assert.match(panelSource, /LazyMarkdownPreview content=\{update\.releaseNotes\}/);
  assert.match(promptSource, /LazyMarkdownPreview/);
});
