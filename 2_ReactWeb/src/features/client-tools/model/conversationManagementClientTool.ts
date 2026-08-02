import type {
  ConversationSession,
  ConversationSessionListResponse,
} from "../../../entities/llm-chat/model/conversation";
import { dispatchProjectConversationUpdated } from "../../../entities/llm-chat/model/projectConversationEvents";
import { stopChatCompletionStream } from "../../../services/llm/stopChatCompletionStream";
import { createProjectConversation } from "../../../services/project/createProjectConversation";
import { deleteProjectConversation } from "../../../services/project/deleteProjectConversation";
import { getProjectConversations } from "../../../services/project/getProjectConversations";
import { getProjectConversationUsageSummary } from "../../../services/project/getProjectConversationUsageSummary";
import { updateProjectConversation } from "../../../services/project/updateProjectConversation";
import { applyAutomaticConversationTitle } from "../../../services/project/applyAutomaticConversationTitle";
import type {
  ClientToolExecutionResult,
  ClientToolRegistration,
} from "./clientToolBridge";
import {
  buildConversationUpdateInput,
  buildChildConversationCreateInput,
  readConversationConfiguration,
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
  getConversationMessagesFilePath,
  getConversationRelationshipFilePath,
  serializeConversationRelationship,
  serializeConversationSession,
  serializeConversationSessionSummary,
  serializeStandaloneConversationSession,
} from "./conversationSessionView";
import {
  selectConversationSessions,
  type ConversationSessionListScope,
} from "./conversationSessionScope";

export const MANAGE_AI_CONVERSATIONS_TOOL_NAME = "manage_ai_conversations";

type ConversationManagementClientToolOptions = {
  getCurrentProjectId: () => string | null;
  onSessionsChanged: (projectId: string) => void | Promise<void>;
  showSession: (projectId: string, sessionId: string) => void | Promise<void>;
};

export function createConversationManagementClientToolRegistration(
  options: ConversationManagementClientToolOptions,
): ClientToolRegistration {
  return {
    name: MANAGE_AI_CONVERSATIONS_TOOL_NAME,
    execute: (request) => executeConversationManagementClientTool(request, options),
  };
}

async function executeConversationManagementClientTool(
  request: Parameters<ClientToolRegistration["execute"]>[0],
  options: ConversationManagementClientToolOptions,
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

    const projectId = readOptionalString(request.project_id) ?? options.getCurrentProjectId();
    if (!projectId) throw new Error("工具请求没有指定项目。");
    failureContext = { project_id: projectId };

    if (action === "name_parent_session") {
      const functionSessionId = readOptionalString(request.session_id);
      if (!functionSessionId) {
        throw new Error("父会话命名请求缺少调用会话。");
      }
      failureContext = sessionFailureContext(projectId, functionSessionId);
      const result = await applyAutomaticConversationTitle(
        projectId,
        functionSessionId,
        { title: readRequiredString(args, "title") },
      );
      await notifySessionsChanged(options, projectId, result.source_session_id, "structure");
      return clientToolSuccess({
        action,
        project_id: projectId,
        function_session_id: functionSessionId,
        ...result,
      });
    }

    const response = await getProjectConversations(projectId);

    if (action === "list_sessions") {
      const scope = readSessionListScope(args.scope);
      const relationDepth = readOptionalRelationDepth(args.relation_depth);
      if (scope === "all" && relationDepth !== null) {
        throw new Error("relation_depth 只用于 scope=related。");
      }
      const callerSessionId = readOptionalString(request.session_id);
      const sessions = selectConversationSessions(
        response,
        callerSessionId,
        scope,
        relationDepth,
      );
      return clientToolSuccess({
        action,
        project_id: projectId,
        active_session_id: response.active_session_id,
        caller_session_id: callerSessionId,
        scope,
        relation_depth: relationDepth,
        count: sessions.length,
        sessions: sessions.map((session) =>
          serializeConversationSessionSummary(response, session),
        ),
      });
    }
    if (action === "get_session_info") {
      const session = requireSession(response, readRequiredString(args, "session_id"));
      failureContext = sessionFailureContext(projectId, session.session_id);
      return clientToolSuccess({
        action,
        project_id: projectId,
        session: serializeConversationSession(response, session),
        relationship: serializeConversationRelationship(response, session.session_id),
        relationship_file_path: getConversationRelationshipFilePath(),
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
        messages_file_path: getConversationMessagesFilePath(session.session_id),
      });
    }
    if (action === "create_session") {
      const callerSessionId = readOptionalString(request.session_id);
      if (!callerSessionId) {
        throw new Error("创建子会话需要调用会话，用于建立父子关系。");
      }
      const source = requireSession(response, callerSessionId);
      const input = await buildChildConversationCreateInput(
        source,
        readConversationConfiguration(args.configuration),
      );
      const created = await createProjectConversation(projectId, {
        ...input,
        activate: false,
        created_by: "ai",
        parent_session_id: callerSessionId,
      });
      await notifySessionsChanged(options, projectId, created.session_id, "structure");
      return clientToolSuccess({
        action,
        project_id: projectId,
        session: serializeStandaloneConversationSession(created, "idle"),
        runtime_status: "idle",
        messages_file_path: getConversationMessagesFilePath(created.session_id),
      });
    }
    const session = requireSession(response, readRequiredString(args, "session_id"));
    failureContext = sessionFailureContext(projectId, session.session_id);
    if (action === "configure_session") {
      const input = await buildConversationUpdateInput(
        session,
        readConversationConfiguration(args.configuration),
      );
      const updated = await updateProjectConversation(projectId, session.session_id, input);
      await notifySessionsChanged(options, projectId, session.session_id, "structure");
      return clientToolSuccess({
        action,
        project_id: projectId,
        session: serializeStandaloneConversationSession(
          updated,
          response.session_states[session.session_id]?.runtime_status ?? "idle",
        ),
        runtime_status: response.session_states[session.session_id]?.runtime_status ?? "idle",
        messages_file_path: getConversationMessagesFilePath(session.session_id),
      });
    }
    if (action === "stop_session") {
      preventSelfTermination(request.session_id, session.session_id, "停止");
      await stopChatCompletionStream(projectId, session.session_id);
      await notifySessionsChanged(options, projectId, session.session_id, "content");
      return clientToolSuccess({
        action,
        project_id: projectId,
        stopped_session_id: session.session_id,
        runtime_status: "idle",
        messages_file_path: getConversationMessagesFilePath(session.session_id),
      });
    }
    if (action === "delete_session") {
      if (args.confirm !== true) {
        throw new Error("删除会话必须明确传入 confirm=true。");
      }
      preventSelfTermination(request.session_id, session.session_id, "删除");
      await deleteProjectConversation(projectId, session.session_id);
      await notifySessionsChanged(options, projectId, session.session_id, "structure");
      return clientToolSuccess({
        action,
        project_id: projectId,
        deleted_session_id: session.session_id,
        messages_file_path: getConversationMessagesFilePath(session.session_id),
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
        messages_file_path: getConversationMessagesFilePath(session.session_id),
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
    messages_file_path: getConversationMessagesFilePath(sessionId),
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

function readSessionListScope(value: unknown): ConversationSessionListScope {
  if (value === undefined || value === null || value === "related") return "related";
  if (value === "all") return "all";
  throw new Error("scope 只支持 related 或 all。");
}

function readOptionalRelationDepth(value: unknown): number | null {
  if (value === undefined || value === null) return null;
  if (!Number.isInteger(value) || Number(value) < 1) {
    throw new Error("关系深度必须是大于等于 1 的整数。");
  }
  return Number(value);
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

async function notifySessionsChanged(
  options: ConversationManagementClientToolOptions,
  projectId: string,
  sessionId: string,
  kind: "content" | "structure",
) {
  dispatchProjectConversationUpdated({ kind, projectId, sessionId });
  await options.onSessionsChanged(projectId);
}
