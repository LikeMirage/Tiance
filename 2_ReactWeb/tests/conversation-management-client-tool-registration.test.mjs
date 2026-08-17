import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import {
  clientToolRequest,
  conversationBranchNode,
  conversationMessage,
  conversationHistoryLocator,
  conversationSession,
  installClientToolTestGlobals,
  installFetchRouter,
  messagePage,
  sessionListResponse,
  usageSummary,
} from "./helpers/conversationClientToolRegistrationFixtures.mjs";

const vite = await createServer({
  appType: "custom",
  logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)),
  server: { middlewareMode: true },
});
const {
  createConversationManagementClientToolRegistration,
} = await vite.ssrLoadModule(
  "/src/features/client-tools/model/conversationManagementClientTool.ts",
);
let restoreGlobals;

before(() => {
  restoreGlobals = installClientToolTestGlobals();
});

after(async () => {
  restoreGlobals();
  await vite.close();
});

test("会话列表默认只返回调用会话的上下级关系和实时摘要", async () => {
  installFetchRouter(({ method, url }) => {
    if (method === "GET" && url.pathname.endsWith("/conversations")) {
      const response = sessionListResponse();
      response.items[0].title = "实时标题";
      return response;
    }
    throw new Error(`未处理的测试请求：${method} ${url}`);
  });
  const registration = createManagementRegistration();

  const result = await registration.execute(clientToolRequest({
    name: "manage_ai_conversations",
    arguments: { action: "list_sessions" },
  }));

  assert.equal(result.ok, true, result.error);
  assert.equal(result.content.active_session_id, "session-a");
  assert.equal(result.content.caller_session_id, "caller-session");
  assert.equal(result.content.scope, "related");
  assert.equal(result.content.relation_depth, null);
  assert.equal(result.content.count, 1);
  assert.deepEqual(result.content.sessions[0], {
    session_id: "session-a",
    title: "实时标题",
    runtime_status: "idle",
  });
});

test("会话列表可显式查看项目全部会话", async () => {
  installFetchRouter(({ method, url }) => {
    if (method === "GET" && url.pathname.endsWith("/conversations")) {
      return sessionListResponse();
    }
    throw new Error(`未处理的测试请求：${method} ${url}`);
  });
  const registration = createManagementRegistration();

  const result = await registration.execute(clientToolRequest({
    name: "manage_ai_conversations",
    sessionId: null,
    arguments: { action: "list_sessions", scope: "all" },
  }));

  assert.equal(result.ok, true, result.error);
  assert.equal(result.content.caller_session_id, null);
  assert.equal(result.content.scope, "all");
  assert.equal(result.content.count, 2);
  assert.deepEqual(
    result.content.sessions.map((session) => session.session_id),
    ["session-a", "caller-session"],
  );
});

test("会话列表关系深度分别限制父级链和自己的下级树", async () => {
  installFetchRouter(({ method, url }) => {
    if (method === "GET" && url.pathname.endsWith("/conversations")) {
      return relatedSessionTreeResponse();
    }
    throw new Error(`未处理的测试请求：${method} ${url}`);
  });
  const registration = createManagementRegistration();

  const directResult = await registration.execute(clientToolRequest({
    name: "manage_ai_conversations",
    arguments: {
      action: "list_sessions",
      relation_depth: 1,
    },
  }));
  const unlimitedResult = await registration.execute(clientToolRequest({
    name: "manage_ai_conversations",
    arguments: { action: "list_sessions" },
  }));

  assert.equal(directResult.ok, true, directResult.error);
  assert.deepEqual(
    directResult.content.sessions.map((session) => session.session_id),
    ["session-a", "child-session"],
  );
  assert.equal(directResult.content.relation_depth, 1);

  assert.equal(unlimitedResult.ok, true, unlimitedResult.error);
  assert.deepEqual(
    unlimitedResult.content.sessions.map((session) => session.session_id),
    ["grandparent-session", "session-a", "child-session", "grandchild-session"],
  );
});

test("会话属性返回详细配置和关系来源", async () => {
  installFetchRouter(({ method, url }) => {
    if (method === "GET" && url.pathname.endsWith("/conversations")) {
      const response = sessionListResponse();
      response.items[0].title = "实时父会话";
      return response;
    }
    throw new Error(`未处理的测试请求：${method} ${url}`);
  });
  const registration = createManagementRegistration();

  const result = await registration.execute(clientToolRequest({
    name: "manage_ai_conversations",
    arguments: {
      action: "get_session_info",
      session_id: "caller-session",
    },
  }));

  assert.equal(result.ok, true, result.error);
  assert.equal(result.content.session.session_id, "caller-session");
  assert.equal(result.content.relationship.relation_kind, "child");
  assert.equal(result.content.relationship.created_by, "ai");
  assert.deepEqual(result.content.relationship.parent_session, {
    session_id: "session-a",
    title: "实时父会话",
  });
});

test("会话管理 registration 返回真实状态、消息与保底路径", async () => {
  installFetchRouter(({ method, url }) => {
    if (method === "GET" && url.pathname.endsWith("/conversations")) {
      return sessionListResponse();
    }
    if (method === "GET" && url.pathname.endsWith("/messages")) {
      assert.ok(Number(url.searchParams.get("limit")) > 0);
      return messagePage([
        conversationMessage("user-1", "user", "问题"),
        conversationMessage("assistant-1", "assistant", "回答"),
      ]);
    }
    if (method === "GET" && url.pathname.endsWith("/usage-summary")) {
      return usageSummary();
    }
    throw new Error(`未处理的测试请求：${method} ${url}`);
  });
  const registration = createManagementRegistration();

  const result = await registration.execute(clientToolRequest({
    name: "manage_ai_conversations",
    arguments: {
      action: "get_session",
      session_id: "session-a",
      message_depth: 1,
      message_format: "content_only",
    },
  }));

  assert.equal(result.ok, true, result.error);
  assert.equal(result.content.session_id, "session-a");
  assert.equal(result.content.title, "测试会话");
  assert.equal(Object.hasOwn(result.content, "session"), false);
  assert.equal(result.content.runtime_status, "idle");
  assert.equal(result.content.message_depth, 1);
  assert.equal(result.content.message_format, "content_only");
  assert.deepEqual(result.content.history_locator, conversationHistoryLocator("session-a"));
  assert.deepEqual(result.content.messages, [{
    user: { message_id: "user-1", role: "user", content: "问题" },
    reply: { message_id: "assistant-1", role: "assistant", content: "回答" },
  }]);
  assert.equal(result.content.usage.total_tokens, 18);
});

test("创建子会话只提交显式覆盖项并由后端继承父配置", async () => {
  let createBody = null;
  installFetchRouter(async ({ init, method, url }) => {
    if (url.pathname.endsWith("/conversations") && method === "GET") {
      return sessionListResponse();
    }
    if (url.pathname.endsWith("/conversations") && method === "POST") {
      createBody = JSON.parse(String(init.body));
      return conversationSession({
        session_id: "session-child",
        sequence_number: 2,
        title: createBody.title,
      });
    }
    throw new Error(`未处理的测试请求：${method} ${url}`);
  });
  const registration = createManagementRegistration();

  const result = await registration.execute(clientToolRequest({
    name: "manage_ai_conversations",
    sessionId: "session-a",
    arguments: {
      action: "create_session",
      configuration: { title: "子会话" },
    },
  }));

  assert.equal(result.ok, true);
  assert.equal(createBody.activate, false);
  assert.equal(createBody.created_by, "ai");
  assert.equal(createBody.parent_session_id, "session-a");
  assert.equal(createBody.title, "子会话");
  assert.equal(Object.hasOwn(createBody, "provider_id"), false);
  assert.equal(Object.hasOwn(createBody, "model_id"), false);
  assert.equal(Object.hasOwn(createBody, "reasoning_mode"), false);
  assert.equal(Object.hasOwn(createBody, "settings"), false);
  assert.equal(result.content.session.session_id, "session-child");
  assert.deepEqual(result.content.history_locator, conversationHistoryLocator("session-child"));
});

test("自动命名功能会话不传目标 ID 并由后端确定父会话", async () => {
  let submittedBody = null;
  installFetchRouter(async ({ init, method, url }) => {
    if (
      method === "POST"
      && url.pathname.endsWith("/conversations/function-session/automatic-title")
    ) {
      submittedBody = JSON.parse(String(init.body));
      return {
        applied: true,
        source_session_id: "session-a",
        status: "completed",
        title: "Token 统计设计",
      };
    }
    throw new Error(`未处理的测试请求：${method} ${url}`);
  });
  const registration = createManagementRegistration();

  const result = await registration.execute(clientToolRequest({
    name: "manage_ai_conversations",
    sessionId: "function-session",
    arguments: {
      action: "name_parent_session",
      title: "Token 统计设计",
    },
  }));

  assert.equal(result.ok, true, result.error);
  assert.deepEqual(submittedBody, {
    title: "Token 统计设计",
  });
  assert.equal(result.content.function_session_id, "function-session");
  assert.equal(result.content.source_session_id, "session-a");
  assert.equal(result.content.title, "Token 统计设计");
});

test("目标会话操作失败时仍保留会话身份与消息路径", async () => {
  installFetchRouter(({ method, url }) => {
    if (method === "GET" && url.pathname.endsWith("/conversations")) {
      return sessionListResponse();
    }
    if (method === "PATCH" && url.pathname.endsWith("/conversations/session-a")) {
      return Response.json(
        { error: { code: "write_failed", message: "会话配置写入失败。" } },
        { status: 500 },
      );
    }
    throw new Error(`未处理的测试请求：${method} ${url}`);
  });
  const registration = createManagementRegistration();

  const result = await registration.execute(clientToolRequest({
    name: "manage_ai_conversations",
    arguments: {
      action: "configure_session",
      session_id: "session-a",
      configuration: { title: "新标题" },
    },
  }));

  assert.equal(result.ok, false);
  assert.equal(result.content.project_id, "project-a");
  assert.equal(result.content.session_id, "session-a");
  assert.deepEqual(result.content.history_locator, conversationHistoryLocator("session-a"));
  assert.match(result.error, /配置写入失败/);
});

function createManagementRegistration(overrides = {}) {
  return createConversationManagementClientToolRegistration({
    showSession: async () => undefined,
    ...overrides,
  });
}

function relatedSessionTreeResponse() {
  const response = sessionListResponse();
  response.items = [
    conversationSession({
      session_id: "grandparent-session",
      sequence_number: 1,
      title: "上两级会话",
    }),
    conversationSession({
      session_id: "session-a",
      sequence_number: 2,
      title: "直接父会话",
    }),
    conversationSession({
      session_id: "sibling-session",
      sequence_number: 3,
      title: "同级会话",
    }),
    conversationSession({
      session_id: "caller-session",
      sequence_number: 4,
      title: "调用会话",
    }),
    conversationSession({
      session_id: "child-session",
      sequence_number: 5,
      title: "直接子会话",
    }),
    conversationSession({
      session_id: "grandchild-session",
      sequence_number: 6,
      title: "下两级会话",
    }),
    conversationSession({
      session_id: "unrelated-session",
      sequence_number: 7,
      title: "无关会话",
    }),
  ];
  response.count = response.items.length;
  response.branch_nodes = [
    conversationBranchNode({
      branch_id: "branch-grandparent",
      tree_id: "tree-related",
      session_id: "grandparent-session",
    }),
    conversationBranchNode({
      branch_id: "branch-a",
      tree_id: "tree-related",
      session_id: "session-a",
      parent_branch_id: "branch-grandparent",
      parent_session_id: "grandparent-session",
      relation_kind: "child",
    }),
    conversationBranchNode({
      branch_id: "branch-sibling",
      tree_id: "tree-related",
      session_id: "sibling-session",
      parent_branch_id: "branch-a",
      parent_session_id: "session-a",
      relation_kind: "child",
    }),
    conversationBranchNode({
      branch_id: "branch-caller",
      tree_id: "tree-related",
      session_id: "caller-session",
      parent_branch_id: "branch-a",
      parent_session_id: "session-a",
      relation_kind: "child",
    }),
    conversationBranchNode({
      branch_id: "branch-child",
      tree_id: "tree-related",
      session_id: "child-session",
      parent_branch_id: "branch-caller",
      parent_session_id: "caller-session",
      relation_kind: "fork",
    }),
    conversationBranchNode({
      branch_id: "branch-grandchild",
      tree_id: "tree-related",
      session_id: "grandchild-session",
      parent_branch_id: "branch-child",
      parent_session_id: "child-session",
      relation_kind: "child",
    }),
    conversationBranchNode({
      branch_id: "branch-unrelated",
      tree_id: "tree-unrelated",
      session_id: "unrelated-session",
    }),
  ];
  return response;
}
