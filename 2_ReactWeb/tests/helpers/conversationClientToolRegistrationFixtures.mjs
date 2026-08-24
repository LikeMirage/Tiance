export function installClientToolTestGlobals() {
  const originalDocument = globalThis.document;
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const testWindow = new EventTarget();
  testWindow.setTimeout = globalThis.setTimeout.bind(globalThis);
  testWindow.clearTimeout = globalThis.clearTimeout.bind(globalThis);
  globalThis.document = new EventTarget();
  globalThis.window = testWindow;

  return () => {
    globalThis.fetch = originalFetch;
    restoreGlobal("document", originalDocument);
    restoreGlobal("window", originalWindow);
  };
}

export function installFetchRouter(route) {
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url);
    const method = (init.method ?? "GET").toUpperCase();
    const routed = await route({ init, method, url });
    if (routed instanceof Response) return routed;
    return Response.json(routed);
  };
}

export function installSessionListFetch({ runtimeStatus = "idle" } = {}) {
  installFetchRouter(({ method, url }) => {
    if (method === "GET" && url.pathname.endsWith("/conversations")) {
      const response = sessionListResponse();
      response.session_states["session-a"].runtime_status = runtimeStatus;
      return response;
    }
    throw new Error(`未处理的测试请求：${method} ${url}`);
  });
}

export function clientToolRequest({
  arguments: argumentsValue,
  name,
  requestId = "request-1",
  sessionId = "caller-session",
  timeoutSeconds = 30,
}) {
  return {
    request_id: requestId,
    call_id: `call-${requestId}`,
    name,
    arguments: JSON.stringify(argumentsValue),
    project_id: "project-a",
    session_id: sessionId,
    timeout_seconds: timeoutSeconds,
  };
}

export function sessionListResponse() {
  return {
    project_id: "project-a",
    count: 2,
    active_session_id: "session-a",
    session_states: {
      "session-a": {
        runtime_status: "idle",
        draft: "",
        updated_at: "2026-07-17T00:00:00Z",
      },
      "caller-session": {
        runtime_status: "running",
        draft: "",
        updated_at: "2026-07-17T00:00:00Z",
      },
    },
    items: [
      conversationSession(),
      conversationSession({
        session_id: "caller-session",
        sequence_number: 2,
        title: "来源会话",
      }),
    ],
    branch_nodes: [
      conversationBranchNode(),
      conversationBranchNode({
        branch_id: "branch-caller",
        tree_id: "tree-caller",
        session_id: "caller-session",
        parent_branch_id: "branch-a",
        parent_session_id: "session-a",
        relation_kind: "child",
        created_by: "ai",
        sibling_index: 1,
      }),
    ],
    message_variants: [],
  };
}

export function conversationBranchNode(overrides = {}) {
  return {
    branch_id: "branch-a",
    tree_id: "tree-a",
    session_id: "session-a",
    parent_branch_id: null,
    parent_session_id: null,
    relation_kind: "root",
    function_type: null,
    created_by: "user",
    history_mode: "empty",
    source_message_id: null,
    sibling_index: 0,
    created_at: "2026-07-17T00:00:00Z",
    deleted_at: null,
    ...overrides,
  };
}

export function conversationSession(overrides = {}) {
  return {
    session_id: "session-a",
    sequence_number: 1,
    title: "测试会话",
    provider_id: "provider-a",
    model_id: "model-a",
    reasoning_mode: "off",
    manual_title: false,
    created_at: "2026-07-17T00:00:00Z",
    updated_at: "2026-07-17T00:00:00Z",
    message_count: 2,
    settings: {
      global_memory_enabled: true,
      memory_context_token_trigger_threshold: 250000,
      memory_compression_enabled: true,
      memory_raw_context_token_reserve: 0,
      project_memory_enabled: true,
      return_cancelled_messages: false,
      return_user_before_cancelled: false,
      streaming_enabled: true,
      auto_collapse_assistant_process: true,
      inject_message_timestamps: true,
      system_prompt: "继承提示词",
      max_output_tokens: 32768,
      temperature: 0.2,
      top_p: 1,
      enabled_tool_names: ["read_text_file"],
      max_tool_calls: 99999,
      tool_approval_mode: "auto_allow_ask",
    },
    ...overrides,
  };
}

export function conversationMessage(messageId, role, content, overrides = {}) {
  return {
    message_id: messageId,
    session_id: "session-a",
    role,
    content,
    provider_id: role === "assistant" ? "provider-a" : null,
    model_id: role === "assistant" ? "model-a" : null,
    status: "done",
    created_at: "2026-07-17T00:00:00Z",
    updated_at: "2026-07-17T00:00:00Z",
    origin_message_id: messageId,
    ...overrides,
  };
}

export function messagePage(items) {
  return {
    project_id: "project-a",
    session_id: "session-a",
    count: items.length,
    total_count: items.length,
    has_more: false,
    next_before_message_id: null,
    items,
  };
}

export function usageSummary() {
  return {
    prompt_tokens: 10,
    completion_tokens: 8,
    total_tokens: 18,
    prompt_cache_hit_tokens: 4,
    prompt_cache_miss_tokens: 6,
    reasoning_tokens: 2,
    record_count: 1,
    by_models: [],
  };
}

export function completedTurn({ outcome, reply, userMessageId }) {
  const user = conversationMessage(userMessageId, "user", "等待回复");
  return {
    assistantMessageId: reply?.message_id ?? null,
    outcome,
    turn: {
      messages: reply ? [user, reply] : [user],
      reply: reply ?? null,
      user,
    },
    userMessageId,
  };
}

export function conversationHistoryLocator(sessionId) {
  return {
    tool_name: "conversation_history_search",
    session_id: sessionId,
  };
}

function restoreGlobal(name, value) {
  if (value === undefined) delete globalThis[name];
  else globalThis[name] = value;
}
