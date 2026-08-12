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
const {
  deriveProviderModelDiscoveryUrl,
  isProviderModelDiscoveryUrlAuto,
} = await vite.ssrLoadModule(
  "/src/features/provider-config/model/deriveProviderModelDiscoveryUrl.ts",
);

after(async () => {
  await vite.close();
});

test("内置供应商使用明确配置的模型列表地址", () => {
  assert.equal(
    deriveProviderModelDiscoveryUrl(
      "https://api.deepseek.com/chat/completions",
      "openai_compatible",
      "https://api.deepseek.com/chat/completions",
      "https://api.deepseek.com/models",
    ),
    "https://api.deepseek.com/models",
  );
  assert.equal(
    deriveProviderModelDiscoveryUrl(
      "https://generativelanguage.googleapis.com/v1beta/models/{model}:{action}",
      "gemini_generate_content",
      "https://generativelanguage.googleapis.com/v1beta/models/{model}:{action}",
      "https://generativelanguage.googleapis.com/v1beta/models",
    ),
    "https://generativelanguage.googleapis.com/v1beta/models",
  );
});

test("自动模式随完整生成地址更新模型列表地址", () => {
  assert.equal(
    deriveProviderModelDiscoveryUrl(
      "https://proxy.example/api/v3/chat/completions",
      "openai_compatible",
    ),
    "https://proxy.example/api/v3/models",
  );
  assert.equal(
    deriveProviderModelDiscoveryUrl(
      "https://proxy.example/custom/inference",
      "openai_compatible",
    ),
    "https://proxy.example/custom/models",
  );
});

test("模型列表地址是否自动由当前保存值判断", () => {
  const generationUrl = "https://proxy.example/v1/responses";
  assert.equal(
    isProviderModelDiscoveryUrlAuto(
      "https://proxy.example/v1/models",
      generationUrl,
      "openai_responses",
    ),
    true,
  );
  assert.equal(
    isProviderModelDiscoveryUrlAuto(
      "https://catalog.example/models",
      generationUrl,
      "openai_responses",
    ),
    false,
  );
  assert.equal(
    isProviderModelDiscoveryUrlAuto("", generationUrl, "openai_responses"),
    false,
  );
  assert.equal(isProviderModelDiscoveryUrlAuto("", "", "openai_responses"), true);
});

test("不完整生成地址不会被擅自补协议或端点", () => {
  assert.equal(
    deriveProviderModelDiscoveryUrl("proxy.example/v1", "openai_compatible"),
    "",
  );
  assert.equal(deriveProviderModelDiscoveryUrl("", "openai_compatible"), "");
});
