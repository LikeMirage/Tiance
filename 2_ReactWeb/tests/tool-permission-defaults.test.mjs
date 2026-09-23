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
const { buildDefaultToolPermissionPolicy, normalizeToolPermissionPolicy } =
  await vite.ssrLoadModule("/src/entities/tool/model/toolPermissions.ts");
after(() => vite.close());

test("新建权限配置只包含询问或允许，保留已有的允许默认值", () => {
  const policy = buildDefaultToolPermissionPolicy();
  assert.equal(policy.fallback, "ask");
  for (const scopes of Object.values(policy.policies)) {
    for (const decision of Object.values(scopes)) {
      assert.ok(["ask", "allow"].includes(decision));
    }
  }
  assert.equal(policy.policies.filesystem_read.workspace_outside, "allow");
  assert.equal(policy.policies.filesystem_write.workspace_inside, "allow");
  assert.equal(policy.policies.tiance_data_delete.unresolved, "ask");
});

test("权限缺项按询问补齐，显式保存的用户选择不被默认值覆盖", () => {
  const policy = normalizeToolPermissionPolicy({
    version: 1, fallback: "ask",
    policies: { filesystem_read: { workspace_inside: "allow" } },
  });
  assert.equal(policy.policies.filesystem_delete.workspace_outside, "ask");
  assert.equal(policy.policies.filesystem_read.workspace_inside, "allow");
});
