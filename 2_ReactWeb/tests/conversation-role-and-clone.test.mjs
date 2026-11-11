import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { installClientToolTestGlobals, installFetchRouter, conversationSession, sessionListResponse, clientToolRequest } from "./helpers/conversationClientToolRegistrationFixtures.mjs";

const vite = await createServer({ appType: "custom", logLevel: "silent", root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
const { createConversationManagementClientToolRegistration } = await vite.ssrLoadModule("/src/features/client-tools/model/conversationManagementClientTool.ts");
let restore;
before(() => { restore = installClientToolTestGlobals(); });
after(async () => { restore(); await vite.close(); });

function setup({ missingRole = false } = {}) {
  const mutations = [];
  installFetchRouter(({ method, url, init }) => {
    if (method === "GET" && url.pathname.endsWith("/conversations")) return sessionListResponse();
    if (method === "GET" && url.pathname === "/api/projects/roles/role-id/configuration") {
      if (missingRole) throw new Error("role no longer exists");
      return { provider_id: "role-provider", model_id: "role-model", reasoning_mode: null,
        settings: { ...conversationSession().settings, system_prompt: "role prompt", temperature: 0.4 } };
    }
    if (url.pathname === "/api/llm/models") return { items: [
      { provider_id: "role-provider", model_id: "role-model", capability_tags: [] },
      { provider_id: "provider-a", model_id: "model-a", capability_tags: [] },
    ] };
    if (url.pathname === "/api/llm/runtime/capabilities") return {
      input_modalities: ["text"], output_formats: ["text"], provider_profile_id: "test",
      reasoning: { supported: url.searchParams.get("model_id") === "model-a", modes: ["off", "high"] },
      max_output_tokens: { supported: true, min: 1, max: 65536 },
      sampling: { supported: true, parameters: ["temperature", "top_p"], disabled_when_reasoning: false }, tool_calling: { supported: true },
    };
    if (["POST", "PATCH"].includes(method)) {
      const body = JSON.parse(init.body); mutations.push({ method, path: url.pathname, body });
      const session = conversationSession({ session_id: "child", ...(body.configuration ?? body) });
      return url.pathname.endsWith("/clone") ? { session, source_message_id: "user-1", state: { draft: "original request" } } : session;
    }
    throw new Error(`Unexpected ${method} ${url}`);
  });
  return mutations;
}

function execute(args) {
  return createConversationManagementClientToolRegistration({ showSession: async () => { throw new Error("must not activate UI"); } }).execute(
    clientToolRequest({ name: "manage_ai_conversations", arguments: args, sessionId: "caller-session" }),
    { signal: new AbortController().signal });
}

test("创建选择完整角色配置，模型来自角色且不激活界面", async () => {
  const mutations = setup();
  const result = await execute({ action: "create_session", configuration: { role_project_id: "role-id" } });
  assert.equal(result.ok, true, result.error);
  const body = mutations[0].body;
  assert.equal(body.model_id, "role-model");
  assert.equal(body.reasoning_mode, null);
  assert.equal(body.settings.system_prompt, "role prompt");
  assert.equal(body.role_project_id, "role-id");
  assert.equal(body.activate, false);
});

test("复刻走独立分支入口，角色加调用者模型再叠加显式设置", async () => {
  const mutations = setup();
  const result = await execute({ action: "clone_session", source_message_id: "user-1", configuration: {
    role_project_id: "role-id", model_source: "caller", settings: { temperature: 0.7 },
  } });
  assert.equal(result.ok, true, result.error);
  assert.equal(mutations.length, 1);
  assert.ok(mutations[0].path.endsWith("/caller-session/clone"));
  const config = mutations[0].body.configuration;
  assert.equal(config.provider_id, "provider-a");
  assert.equal(config.model_id, "model-a");
  assert.equal(config.settings.system_prompt, "role prompt");
  assert.equal(config.settings.temperature, 0.7);
  assert.equal(result.content.activated, false);
  assert.equal(result.content.state.draft, "original request");
});

test("修改指定会话能换角色并继承调用者模型，非目标会话模型", async () => {
  const mutations = setup();
  const result = await execute({ action: "configure_session", session_id: "session-a",
    configuration: { role_project_id: "role-id", model_source: "caller" } });
  assert.equal(result.ok, true, result.error);
  assert.equal(mutations.length, 1);
  assert.equal(mutations[0].method, "PATCH");
  assert.ok(mutations[0].path.endsWith("/session-a"));
  assert.equal(mutations[0].body.model_id, "model-a");
  assert.equal(mutations[0].body.settings.system_prompt, "role prompt");
});

test("角色不存在、模型来源冲突或模型不支持的推理配置均先拒绝再创建", async () => {
  let mutations = setup({ missingRole: true });
  assert.equal((await execute({ action: "clone_session", configuration: { role_project_id: "role-id" } })).ok, false);
  assert.equal(mutations.length, 0);
  for (const configuration of [
    { model_source: "caller", model_id: "model-a", provider_id: "provider-a" },
    { role_project_id: "role-id", reasoning_mode: "high" },
  ]) {
    mutations = setup();
    assert.equal((await execute({ action: "create_session", configuration })).ok, false);
    assert.equal(mutations.length, 0);
  }
});
