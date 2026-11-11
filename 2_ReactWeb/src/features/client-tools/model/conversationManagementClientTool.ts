import { fetchJson } from "../../../services/http/httpClient";
import type {
  ConversationSession,
  ConversationSessionListResponse,
} from "../../../entities/llm-chat/model/conversation";
import { dispatchProjectConversationUpdated } from "../../../entities/llm-chat/model/projectConversationEvents";
import { stopChatCompletionStream } from "../../../services/llm/stopChatCompletionStream";
import { createProjectConversation } from "../../../services/project/createProjectConversation";
import { getProjectConversations } from "../../../services/project/getProjectConversations";
import { getProjectConversationUsageSummary } from "../../../services/project/getProjectConversationUsageSummary";
import { updateProjectConversation } from "../../../services/project/updateProjectConversation";
import type {
  ClientToolExecutionResult,
  ClientToolRegistration,
} from "./clientToolBridge";
import {
  buildConversationUpdateInput,
  buildChildConversationCreateInput,
  readConversationConfiguration,
  resolveCallerModel,
} from "./conversationConfiguration";
import {
  clientToolFailure,
  clientToolSuccess,
  parseClientToolArguments,
  readOptionalString,
  readPositiveInteger,
  readRequiredString,
} from "./conversationClientToolValues";
import { loadRecentCompletedConversationTurns } from "./loadConversationMessageTurns";
import {
  serializeConversationTurns,
  type ConversationMessageFormat,
} from "./conversationMessageTurns";
import { queryConversationModels } from "./conversationModelQuery";
import {
  getConversationHistoryLocator,
  serializeConversationRelationship,
  serializeConversationSession,
  serializeStandaloneConversationSession,
} from "./conversationSessionView";
import { executeConversationSelection } from "./conversationSelectionClientTool";

export const MANAGE_AI_CONVERSATIONS_TOOL_NAME = "manage_ai_conversations";
export const CONVERSATION_MANAGEMENT_CAPABILITY = Object.freeze({
  name: "conversation.management",
  version: 3,
});

type ConversationManagementClientToolOptions = {
  showSession: (projectId: string, sessionId: string) => void | Promise<void>;
};

export function createConversationManagementClientToolRegistration(
  options: ConversationManagementClientToolOptions,
): ClientToolRegistration {
  return {
    capability: CONVERSATION_MANAGEMENT_CAPABILITY,
    execute: (request, context) => executeConversationManagementClientTool(request, options, context?.signal),
  };
}

async function executeConversationManagementClientTool(
  request: Parameters<ClientToolRegistration["execute"]>[0],
  options: ConversationManagementClientToolOptions,
  signal?: AbortSignal,
): Promise<ClientToolExecutionResult> {
  let action = "";
  let failureContext: Record<string, unknown> = {};
  try {
    const args = parseClientToolArguments(request.arguments);
    action = readRequiredString(args, "action");
    if (action === "query_models") {
      return clientToolSuccess({
        action,
        ...await queryConversationModels({
          providerId: readOptionalString(args.provider_id),
          modelId: readOptionalString(args.model_id),
          query: readOptionalString(args.query),
        }),
      });
    }

    const projectId = readOptionalString(request.project_id);
    if (!projectId) throw new Error("工具请求没有指定项目。");
    failureContext = { project_id: projectId };

    if (["list_sessions", "preview_delete", "delete_session"].includes(action)) {
      return await executeConversationSelection(projectId, readOptionalString(request.session_id), args, signal);
    }
    const response = await getProjectConversations(projectId, signal);
    if (action === "get_session_info") {
      const session = requireSession(response, readRequiredString(args, "session_id"));
      failureContext = sessionFailureContext(projectId, session.session_id);
      return clientToolSuccess({
        action,
        project_id: projectId,
        session: serializeConversationSession(response, session),
        relationship: serializeConversationRelationship(response, session.session_id),
      });
    }
    if (action === "get_session") {
      const session = requireSession(response, readRequiredString(args, "session_id"));
      failureContext = sessionFailureContext(projectId, session.session_id);
      const messageDepth = readPositiveInteger(args.message_depth, 1);
      const messageFormat = readMessageFormat(args.message_format);
      const [messagePage, usage] = await Promise.all([
        loadRecentCompletedConversationTurns(projectId, session.session_id, messageDepth),
        getProjectConversationUsageSummary(projectId, session.session_id),
      ]);
      return clientToolSuccess({
        action,
        project_id: projectId,
        session_id: session.session_id,
        title: session.title,
        runtime_status: response.session_states[session.session_id]?.runtime_status ?? "idle",
        message_depth: messagePage.turns.length,
        message_format: messageFormat,
        messages: serializeConversationTurns(messagePage.turns, messageFormat),
        loaded_message_count: messagePage.loadedMessageCount,
        history_exhausted: messagePage.historyExhausted,
        usage,
        history_locator: getConversationHistoryLocator(session.session_id),
      });
    }
    if (action === "create_session" || action === "clone_session") {
      const callerSessionId = readOptionalString(request.session_id);
      if (!callerSessionId) {
        throw new Error("创建子会话需要调用会话，用于建立父子关系。");
      }
      const source = requireSession(response, callerSessionId);
      const input = await buildChildConversationCreateInput(
        source,
        resolveCallerModel(readConversationConfiguration(args.configuration), source),
      );
      if (action === "clone_session") {
        const result = await fetchJson<{ session: ConversationSession; source_message_id: string; state: unknown }>(
          `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(callerSessionId)}/clone`,
          { method: "POST", body: JSON.stringify({ source_message_id: args.source_message_id ?? null, configuration: input }) },
        );
        notifySessionsChanged(projectId, result.session.session_id, "structure");
        return clientToolSuccess({ action, project_id: projectId, ...result,
          history_boundary: "before_source_user_message", activated: false,
          guidance: "已复制源用户消息之前的历史；该用户消息与引用保存在新会话草稿。新会话属于 AI 子会话，尚未运行。用会话交互工具发送任务即可继续。" });
      }
      const created = await createProjectConversation(projectId, {
        ...input,
        activate: false,
        created_by: "ai",
        parent_session_id: callerSessionId,
      });
      notifySessionsChanged(projectId, created.session_id, "structure");
      return clientToolSuccess({
        action,
        project_id: projectId,
        session: serializeStandaloneConversationSession(created, "idle"),
        runtime_status: "idle",
        history_locator: getConversationHistoryLocator(created.session_id),
      });
    }
    const session = requireSession(response, readRequiredString(args, "session_id"));
    failureContext = sessionFailureContext(projectId, session.session_id);
    if (action === "configure_session") {
      const input = await buildConversationUpdateInput(
        session,
        resolveCallerModel(readConversationConfiguration(args.configuration), requireSession(response, readRequiredString(request, "session_id"))),
      );
      const updated = await updateProjectConversation(projectId, session.session_id, input);
      notifySessionsChanged(projectId, session.session_id, "structure");
      return clientToolSuccess({
        action,
        project_id: projectId,
        session: serializeStandaloneConversationSession(
          updated,
          response.session_states[session.session_id]?.runtime_status ?? "idle",
        ),
        runtime_status: response.session_states[session.session_id]?.runtime_status ?? "idle",
        history_locator: getConversationHistoryLocator(session.session_id),
      });
    }
    if (action === "stop_session") {
      preventSelfTermination(request.session_id, session.session_id, "停止");
      await stopChatCompletionStream(projectId, session.session_id);
      notifySessionsChanged(projectId, session.session_id, "content");
      return clientToolSuccess({
        action,
        project_id: projectId,
        stopped_session_id: session.session_id,
        runtime_status: "idle",
        history_locator: getConversationHistoryLocator(session.session_id),
      });
    }
    if (action === "show_session") {
      await options.showSession(projectId, session.session_id);
      return clientToolSuccess({
        action,
        project_id: projectId,
        session_id: session.session_id,
        shown: true,
        runtime_status: response.session_states[session.session_id]?.runtime_status ?? "idle",
        history_locator: getConversationHistoryLocator(session.session_id),
      });
    }
    throw new Error(`不支持的会话管理操作：${action}`);
  } catch (error) {
    return clientToolFailure(error, { action, ...failureContext });
  }
}

function sessionFailureContext(projectId: string, sessionId: string) {
  return {
    project_id: projectId,
    session_id: sessionId,
    history_locator: getConversationHistoryLocator(sessionId),
  };
}

function requireSession(
  response: ConversationSessionListResponse,
  sessionId: string,
): ConversationSession {
  const session = response.items.find((item) => item.session_id === sessionId);
  if (!session) throw new Error(`会话不存在：${sessionId}`);
  return session;
}

function readMessageFormat(value: unknown): ConversationMessageFormat {
  if (value === undefined || value === null || value === "content_only") return "content_only";
  if (value === "full") return "full";
  throw new Error("message_format 只支持 content_only 或 full。");
}

function preventSelfTermination(
  callerSessionId: string | null | undefined,
  targetSessionId: string,
  actionLabel: string,
) {
  if (callerSessionId === targetSessionId) {
    throw new Error(`工具调用尚未返回，不能${actionLabel}当前调用会话。`);
  }
}

function notifySessionsChanged(
  projectId: string,
  sessionId: string,
  kind: "content" | "structure",
) {
  dispatchProjectConversationUpdated({ kind, projectId, sessionId });
}
