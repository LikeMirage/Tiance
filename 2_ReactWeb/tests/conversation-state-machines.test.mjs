import assert from "node:assert/strict";
import test from "node:test";

import {
  initialConversationSelectionState,
  reduceConversationSelection,
} from "../src/features/ai-panel/model/conversationSelectionMachine.ts";
import {
  initialConversationSessionLoadState,
  reduceConversationSessionLoad,
} from "../src/features/ai-panel/model/conversationSessionLoadMachine.ts";

const request = (requestId, projectId, sessionId) => ({
  requestId,
  source: "overview",
  target: { projectId, sessionId },
});

test("会话选择只接受最后一次请求的确认", () => {
  let state = reduceConversationSelection(initialConversationSelectionState, {
    type: "request",
    request: request(1, "project-a", "session-a"),
  });
  state = reduceConversationSelection(state, {
    type: "request",
    request: request(2, "project-a", "session-b"),
  });
  state = reduceConversationSelection(state, {
    type: "confirmed",
    requestId: 1,
    target: { projectId: "project-a", sessionId: "session-a" },
  });
  assert.equal(state.status, "selecting");
  assert.equal(state.request.requestId, 2);

  state = reduceConversationSelection(state, {
    type: "confirmed",
    requestId: 2,
    target: { projectId: "project-a", sessionId: "session-b" },
  });
  assert.deepEqual(state, {
    current: { projectId: "project-a", sessionId: "session-b" },
    status: "stable",
  });
});

test("切到其他项目会取消尚未完成的会话选择", () => {
  let state = reduceConversationSelection(initialConversationSelectionState, {
    type: "sync_current",
    target: { projectId: "project-a", sessionId: "session-a" },
  });
  state = reduceConversationSelection(state, {
    type: "request",
    request: request(3, "project-b", "session-b"),
  });
  state = reduceConversationSelection(state, {
    type: "project_changed",
    projectId: "project-a",
  });
  assert.equal(state.status, "selecting");
  assert.equal(state.phase, "switching_project");

  state = reduceConversationSelection(state, {
    type: "project_ready",
    requestId: 3,
  });
  state = reduceConversationSelection(state, {
    type: "project_changed",
    projectId: "project-a",
  });
  assert.deepEqual(state, {
    current: { projectId: "project-a", sessionId: "session-a" },
    status: "stable",
  });
});

test("目标会话缺失会进入明确失败终态并保留可用回退", () => {
  let state = reduceConversationSelection(initialConversationSelectionState, {
    type: "request",
    request: request(4, "project-a", "missing-session"),
  });
  state = reduceConversationSelection(state, {
    type: "failed",
    current: { projectId: "project-a", sessionId: "fallback-session" },
    message: "目标会话不存在",
    reason: "missing",
    requestId: 4,
  });
  assert.equal(state.status, "failed");
  assert.deepEqual(state.current, {
    projectId: "project-a",
    sessionId: "fallback-session",
  });
  assert.equal(state.failure.reason, "missing");
});

test("项目切换被用户取消后会话选择回到稳定状态", () => {
  let state = reduceConversationSelection(initialConversationSelectionState, {
    type: "sync_current",
    target: { projectId: "project-a", sessionId: "session-a" },
  });
  state = reduceConversationSelection(state, {
    type: "request",
    request: request(5, "project-b", "session-b"),
  });
  state = reduceConversationSelection(state, {
    type: "cancelled",
    requestId: 5,
  });

  assert.deepEqual(state, {
    current: { projectId: "project-a", sessionId: "session-a" },
    status: "stable",
  });
});

test("直接切换项目会立即清除旧项目的可见会话", () => {
  let state = reduceConversationSelection(initialConversationSelectionState, {
    type: "sync_current",
    target: { projectId: "project-a", sessionId: "session-a" },
  });
  state = reduceConversationSelection(state, {
    type: "project_changed",
    projectId: "project-b",
  });

  assert.deepEqual(state, {
    current: { projectId: "project-b", sessionId: null },
    status: "stable",
  });
});

test("旧加载响应不能结束新的项目加载", () => {
  let state = reduceConversationSessionLoad(initialConversationSessionLoadState, {
    type: "begin",
    hasSnapshot: false,
    projectId: "project-a",
    requestId: 1,
  });
  state = reduceConversationSessionLoad(state, {
    type: "begin",
    hasSnapshot: true,
    projectId: "project-b",
    requestId: 2,
  });
  state = reduceConversationSessionLoad(state, {
    type: "ready",
    projectId: "project-a",
    requestId: 1,
  });
  assert.deepEqual(state, {
    hasSnapshot: true,
    projectId: "project-b",
    requestId: 2,
    status: "loading",
  });

  state = reduceConversationSessionLoad(state, {
    type: "failed",
    hasSnapshot: true,
    message: "超时",
    projectId: "project-b",
    requestId: 2,
  });
  assert.equal(state.status, "error");
  assert.equal(state.message, "超时");
});
