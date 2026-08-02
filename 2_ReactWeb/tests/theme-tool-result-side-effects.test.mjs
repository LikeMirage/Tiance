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
  "/src/features/ai-panel/model/chatStreamEventSideEffects.ts",
);

after(async () => {
  await vite.close();
});

test("直接调用主题工具切换成功后请求刷新当前主题", () => {
  const detail = readThemeRefreshRequestFromToolResult(toolResultEvent({
    name: "theme_designer",
    arguments: { action: "switch", theme_id: "dark-gold" },
    content: {
      ok: true,
      data: { action: "switch", theme_id: "dark-gold" },
    },
  }));

  assert.deepEqual(detail, {
    reason: "theme_designer",
    themeId: "dark-gold",
  });
});

test("动态工具包装的主题切换成功后请求刷新当前主题", () => {
  const detail = readThemeRefreshRequestFromToolResult(dynamicToolResultEvent({
    arguments: { action: "switch", theme_id: "dark-gold" },
    result: {
      ok: true,
      data: { action: "switch", theme_id: "dark-gold" },
    },
  }));

  assert.deepEqual(detail, {
    reason: "theme_designer",
    themeId: "dark-gold",
  });
});

test("动态工具包装的当前主题编辑成功后请求重新应用主题", () => {
  const detail = readThemeRefreshRequestFromToolResult(dynamicToolResultEvent({
    arguments: {
      action: "edit",
      theme_id: "light",
      updates: { "tokens.accent.base": "#4466aa" },
    },
    result: {
      ok: true,
      data: {
        action: "edit",
        theme_id: "light",
        changed_fields: ["tokens.accent.base"],
      },
    },
  }));

  assert.deepEqual(detail, {
    reason: "theme_designer",
    themeId: "light",
  });
});

test("动态工具包装的主题配色派生成功后请求重新应用主题", () => {
  const detail = readThemeRefreshRequestFromToolResult(dynamicToolResultEvent({
    arguments: {
      action: "derive_palette",
      theme_id: "light",
      palette: {
        background: "#F3F5F7",
        panel: "#FFFFFF",
        text: "#20262C",
        accent: "#356A8A",
      },
    },
    result: {
      ok: true,
      data: {
        action: "derive_palette",
        theme_id: "light",
        derived_token_count: 67,
      },
    },
  }));

  assert.deepEqual(detail, {
    reason: "theme_designer",
    themeId: "light",
  });
});

test("主题只读操作和其他动态工具不会触发主题刷新", () => {
  const listResult = readThemeRefreshRequestFromToolResult(dynamicToolResultEvent({
    arguments: { action: "list" },
    result: {
      ok: true,
      data: { action: "list", active_theme_id: "light" },
    },
  }));
  const otherToolResult = readThemeRefreshRequestFromToolResult(dynamicToolResultEvent({
    toolName: "read_file",
    arguments: { file_path: "README.md" },
    result: { ok: true, data: { content: "README" } },
  }));

  assert.equal(listResult, null);
  assert.equal(otherToolResult, null);
});

test("失败的主题动态工具结果不会触发主题刷新", () => {
  const outerFailure = readThemeRefreshRequestFromToolResult(dynamicToolResultEvent({
    ok: false,
    arguments: { action: "switch", theme_id: "missing" },
    result: {
      ok: false,
      error: "Theme not found",
    },
  }));
  const targetFailure = readThemeRefreshRequestFromToolResult(dynamicToolResultEvent({
    arguments: { action: "switch", theme_id: "missing" },
    result: {
      ok: false,
      error: "Theme not found",
    },
  }));

  assert.equal(outerFailure, null);
  assert.equal(targetFailure, null);
});

function dynamicToolResultEvent({
  toolName = "theme_designer",
  arguments: targetArguments,
  result,
  ok = true,
}) {
  return toolResultEvent({
    name: "execute_dynamic_tool",
    ok,
    arguments: {
      tool_name: toolName,
      arguments: targetArguments,
    },
    content: {
      ok,
      data: {
        tool_name: toolName,
        arguments: targetArguments,
        result,
      },
    },
  });
}

function toolResultEvent({
  name,
  arguments: toolArguments,
  content,
  ok = true,
}) {
  return {
    kind: "tool_result",
    tool_result: {
      call_id: "call-theme",
      name,
      arguments: JSON.stringify(toolArguments),
      ok,
      content: JSON.stringify(content),
    },
  };
}
