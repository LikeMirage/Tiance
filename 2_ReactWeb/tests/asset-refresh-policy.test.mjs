import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const vite = await createServer({
  appType: "custom",
  logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)),
  server: { middlewareMode: true },
});
const { decideAssetRefresh } = await vite.ssrLoadModule(
  "/src/features/document-tabs/model/assetRefreshPolicy.ts",
);

after(async () => {
  await vite.close();
});

test("明确的文件路径事件刷新对应资源", () => {
  assert.deepEqual(decideAssetRefresh({
    currentMtimeMs: null,
    hasDetailedChange: true,
    metadata: { exists: true, mtimeMs: null },
  }), { kind: "refresh", mtimeMs: null });
});

test("overflow 核对时元数据未知不会误刷新资源", () => {
  assert.deepEqual(decideAssetRefresh({
    currentMtimeMs: null,
    hasDetailedChange: false,
    metadata: { exists: null, mtimeMs: null },
  }), { kind: "ignore" });
});

test("overflow 只刷新确认修改或删除的资源", () => {
  assert.deepEqual(decideAssetRefresh({
    currentMtimeMs: 100,
    hasDetailedChange: false,
    metadata: { exists: true, mtimeMs: 100 },
  }), { kind: "ignore" });
  assert.deepEqual(decideAssetRefresh({
    currentMtimeMs: 100,
    hasDetailedChange: false,
    metadata: { exists: true, mtimeMs: 101 },
  }), { kind: "refresh", mtimeMs: 101 });
  assert.deepEqual(decideAssetRefresh({
    currentMtimeMs: 100,
    hasDetailedChange: false,
    metadata: { exists: false, mtimeMs: null },
  }), { kind: "mark-missing" });
});
