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
  createClientToolRegistry,
} = await vite.ssrLoadModule(
  "/src/features/client-tools/model/clientToolBridge.ts",
);

after(async () => {
  await vite.close();
});

test("客户端工具注册表按能力合同分派且不会依赖注册顺序", async () => {
  const calls = [];
  const registry = createClientToolRegistry([
    registration("tool_b", calls),
    registration("tool_a", calls),
  ]);

  assert.deepEqual(registry.capabilities, [
    { name: "tool_b", version: 1 },
    { name: "tool_a", version: 1 },
  ]);

  const result = await registry.execute(request("tool_a"));
  assert.equal(result.ok, true);
  assert.deepEqual(result.content, { handled_by: "tool_a" });
  assert.deepEqual(calls, ["tool_a"]);
});

test("组合执行器对未注册工具返回稳定错误", async () => {
  const executor = createClientToolRegistry([]).execute;
  const result = await executor(request("missing_tool"));

  assert.equal(result.ok, false);
  assert.deepEqual(result.content, { tool: "missing_tool" });
  assert.match(result.error, /缺少前端能力 missing_tool v1/);
});

test("重复能力在注册阶段立即失败", () => {
  assert.throws(
    () => createClientToolRegistry([
      registration("same_tool", []),
      registration("same_tool", []),
    ]),
    /能力重复注册：same_tool/,
  );
});

test("注册名称不允许空值或隐蔽首尾空白", () => {
  assert.throws(
    () => createClientToolRegistry([registration("", [])]),
    /不能为空/,
  );
  assert.throws(
    () => createClientToolRegistry([registration(" tool_a ", [])]),
    /首尾空白/,
  );
});

function registration(name, calls) {
  return {
    capability: { name, version: 1 },
    execute: async () => {
      calls.push(name);
      return { ok: true, content: { handled_by: name } };
    },
  };
}

function request(name) {
  return {
    request_id: `request-${name}`,
    call_id: `call-${name}`,
    name,
    arguments: "{}",
    client_capability: { name, min_version: 1 },
  };
}
