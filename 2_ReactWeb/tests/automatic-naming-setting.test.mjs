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

test("旧角色省略命名开关时仍启用，关闭后编辑保存其他选项不会重新打开", () => {
  const original = parseRoleConfigurationSection("response", '{"streaming_enabled":true}');
  assert.equal(original.automatic_naming_enabled, true);
  const saved = formatRoleConfigurationSection({ ...original, automatic_naming_enabled: false });
  const reopened = parseRoleConfigurationSection("response", saved);
  const edited = formatRoleConfigurationSection({ ...reopened, streaming_enabled: false });
  assert.equal(parseRoleConfigurationSection("response", edited).automatic_naming_enabled, false);
});

test("会话配置默认值不会盖掉已保存的关闭选择", () => {
  assert.equal(resolveSessionSettings(null).automatic_naming_enabled, true);
  assert.equal(resolveSessionSettings({ settings: { automatic_naming_enabled: false } }).automatic_naming_enabled, false);
});
