import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const vite = await createServer({
  appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)),
  server: { middlewareMode: true },
});
after(() => vite.close());
const { parseRoleConfigurationSection, formatRoleConfigurationSection } = await vite.ssrLoadModule(
  "/src/entities/role-configuration/model/roleConfiguration.ts",
);
const { resolveSessionSettings } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/sessionSettings.ts",
);
const { buildConversationRunRequest } = await vite.ssrLoadModule(
  "/src/features/conversation-runtime/model/conversationRunRequest.ts",
);
const { readConversationConfiguration } = await vite.ssrLoadModule(
  "/src/features/client-tools/model/conversationConfiguration.ts",
);

test("重试间隔在角色读取、编辑保存和重新打开后保持，0 不会被默认值覆盖", () => {
  const original = parseRoleConfigurationSection("response", '{}');
  assert.equal(original.upstream_retry_interval_seconds, 5);
  for (const seconds of [0, 17]) {
    const saved = formatRoleConfigurationSection({ ...original, upstream_retry_interval_seconds: seconds });
    const reopened = parseRoleConfigurationSection("response", saved);
    assert.equal(reopened.upstream_retry_interval_seconds, seconds);
    const edited = formatRoleConfigurationSection({ ...reopened, streaming_enabled: false });
    assert.equal(parseRoleConfigurationSection("response", edited).upstream_retry_interval_seconds, seconds);
  }
});

test("会话设置和模型请求传递实际间隔，前端能力桥允许此配置", () => {
  assert.equal(resolveSessionSettings(null).upstream_retry_interval_seconds, 5);
  for (const seconds of [0, 17]) {
    const settings = resolveSessionSettings({ settings: { upstream_retry_interval_seconds: seconds } });
    const request = buildConversationRunRequest({ settings, messages: [], modelId: "m", providerId: "p",
      projectId: "project", sessionId: "session", reasoningMode: null, clientCapabilities: [] });
    assert.equal(request.upstream_retry_interval_seconds, seconds);
    assert.equal(readConversationConfiguration({ settings: { upstream_retry_interval_seconds: seconds } })
      .settings.upstream_retry_interval_seconds, seconds);
  }
});
