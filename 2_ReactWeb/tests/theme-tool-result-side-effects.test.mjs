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
  readThemeRefreshRequestFromToolResult,
} = await vite.ssrLoadModule(
  "/src/features/conversation-runtime/model/chatStreamEventSideEffects.ts",
);

after(async () => {
  await vite.close();
});

test("工具可用通用资源失效通知请求主题刷新", () => {
  const detail = readThemeRefreshRequestFromToolResult(toolResultEvent({
    name: "any_tool_name",
    content: {
      ok: true,
      resource_invalidations: [
        { resource: "themes", resource_id: "dark-gold" },
      ],
    },
  }));

  assert.deepEqual(detail, {
    reason: "resource_invalidation",
    themeId: "dark-gold",
  });
});

test("动态工具包装中的通用资源失效通知同样生效", () => {
  const detail = readThemeRefreshRequestFromToolResult(toolResultEvent({
    name: "execute_dynamic_tool",
    content: {
      ok: true,
      data: {
        result: {
          ok: true,
          resource_invalidations: [{ resource: "themes" }],
        },
      },
    },
  }));

  assert.deepEqual(detail, {
    reason: "resource_invalidation",
    themeId: null,
  });
});

test("工具名称和动作参数不能触发隐藏的主题特殊分支", () => {
  const detail = readThemeRefreshRequestFromToolResult(toolResultEvent({
    name: "theme_designer",
    content: {
      ok: true,
      data: { action: "switch", theme_id: "dark-gold" },
    },
  }));

  assert.equal(detail, null);
});

test("失败结果和其他资源失效通知不会刷新主题", () => {
  const failed = readThemeRefreshRequestFromToolResult(toolResultEvent({
    name: "generic_tool",
    ok: false,
    content: {
      resource_invalidations: [{ resource: "themes" }],
    },
  }));
  const filesChanged = readThemeRefreshRequestFromToolResult(toolResultEvent({
    name: "generic_tool",
    content: {
      resource_invalidations: [{ resource: "workspace_files" }],
    },
  }));

  assert.equal(failed, null);
  assert.equal(filesChanged, null);
});

function toolResultEvent({ name, content, ok = true }) {
  return {
    kind: "tool_result",
    tool_result: {
      call_id: "call-resource",
      name,
      arguments: "{}",
      ok,
      content: JSON.stringify(content),
    },
  };
}
