import { emitLlmUsageChanged } from "../../../entities/llm-usage/model/usageRefreshEvents";
import { dispatchProjectConversationUpdated } from "../../../entities/llm-chat/model/projectConversationEvents";
import { getProjectConversations } from "../../../services/project/getProjectConversations";
import type { ChatClientCapability } from "../../../entities/llm-chat/model/chatCompletion";
import type {
  ClientToolExecutionResult,
  ClientToolExecutor,
  ClientToolRegistration,
} from "./clientToolBridge";
import { ConversationBackgroundRunRegistry } from "./conversationBackgroundRun";
import type {
  ConversationBackgroundRunResult,
} from "./conversationBackgroundRun";
import {
  clientToolFailure,
  clientToolSuccess,
  parseClientToolArguments,
  readBoolean,
  readOptionalString,
  readRequiredString,
} from "./conversationClientToolValues";
import { getConversationHistoryLocator } from "./conversationSessionView";

export const INTERACT_AI_CONVERSATION_TOOL_NAME = "interact_ai_conversation";
export const CONVERSATION_INTERACTION_CAPABILITY = Object.freeze({
  name: "conversation.interaction",
  version: 1,
});

type ConversationInteractionClientToolOptions = {
  backgroundRuns: ConversationBackgroundRunRegistry;
  getClientToolExecutor: () => ClientToolExecutor | null;
  getClientCapabilities: () => readonly ChatClientCapability[];
  onSessionRuntimeStatusChanged: (
    projectId: string,
    sessionId: string,
    status: "idle" | "running" | "error",
  ) => void;
};

export function createConversationInteractionClientToolRegistration(
  options: ConversationInteractionClientToolOptions,
): ClientToolRegistration {
  return {
    capability: CONVERSATION_INTERACTION_CAPABILITY,
    execute: (request) => executeConversationInteractionClientTool(request, options),
  };
}
async function executeConversationInteractionClientTool(
  request: Parameters<ClientToolRegistration["execute"]>[0],
  options: ConversationInteractionClientToolOptions,
): Promise<ClientToolExecutionResult> {
  let action = "";
  let failureContext: Record<string, unknown> = {};
  try {
    const args = parseClientToolArguments(request.arguments);
    action = readRequiredString(args, "action");
    const projectId = readOptionalString(request.project_id);
    if (!projectId) throw new Error("工具请求没有指定项目。");
    const response = await getProjectConversations(projectId);

    if (action !== "send") {
      throw new Error(`不支持的会话交互操作：${action}`);
    }

    const sessionId = readRequiredString(args, "session_id");
    const message = readRequiredString(args, "message");
    const waitForReply = readBoolean(args.wait_for_reply, true);
    const sourceSessionId = readOptionalString(request.session_id);
    if (!sourceSessionId) throw new Error("工具请求没有指定来源会话。");
    const sourceSession = response.items.find((item) => item.session_id === sourceSessionId);
    if (!sourceSession) throw new Error(`来源会话不存在：${sourceSessionId}`);
    const session = response.items.find((item) => item.session_id === sessionId);
    if (!session) throw new Error(`会话不存在：${sessionId}`);
    const historyLocator = getConversationHistoryLocator(sessionId);
    failureContext = {
      project_id: projectId,
      session_id: sessionId,
      history_locator: historyLocator,
    };
    const runtimeStatus = response.session_states[sessionId]?.runtime_status ?? "idle";
    const run = options.backgroundRuns.startOrResume({
      clientToolExecutor: options.getClientToolExecutor,
      clientCapabilities: options.getClientCapabilities,
      initialStrategy: runtimeStatus === "running" ? "resume_then_start" : "start",
      message: appendSourceSessionAttribution(message, {
        sessionId: sourceSession.session_id,
        title: sourceSession.title,
      }),
      projectId,
      session,
      userMessageId: `client_${request.request_id}`,
      onStarted: () => {
        options.onSessionRuntimeStatusChanged(projectId, sessionId, "running");
        dispatchProjectConversationUpdated({
          kind: "content",
          projectId,
          sessionId,
        });
      },
      onSettled: (outcome) => {
        if (outcome) {
          options.onSessionRuntimeStatusChanged(
            projectId,
            sessionId,
            outcome === "error" ? "error" : "idle",
          );
        }
        dispatchProjectConversationUpdated({
          kind: "content",
          projectId,
          sessionId,
        });
        emitLlmUsageChanged({
          providerId: session.provider_id,
          modelId: session.model_id,
        });
      },
    });
    const started = await run.started;
    if (!waitForReply) {
      if (!started.running) {
        return clientToolSuccess(serializeCompletedSend(
          action,
          projectId,
          sessionId,
          historyLocator,
          await run.completion,
          false,
        ));
      }
      return clientToolSuccess({
        action,
        project_id: projectId,
        session_id: sessionId,
        accepted: true,
        wait_for_reply: false,
        runtime_status: "running",
        outcome: "still_running",
        user_message_id: started.userMessageId,
        history_locator: historyLocator,
      });
    }

    const waited = await run.completion;
    return clientToolSuccess(serializeCompletedSend(
      action,
      projectId,
      sessionId,
      historyLocator,
      waited,
      true,
    ));
  } catch (error) {
    return clientToolFailure(error, { action, ...failureContext });
  }
}

function appendSourceSessionAttribution(
  message: string,
  source: { sessionId: string; title: string },
): string {
  const sourceTitle = source.title.replace(/[\r\n]+/g, " ").trim();
  return [
    message,
    "",
    `本条消息来源会话名称：${sourceTitle}`,
    `本条消息来源会话 ID：${source.sessionId}`,
  ].join("\n");
}

function serializeCompletedSend(
  action: string,
  projectId: string,
  sessionId: string,
  historyLocator: ReturnType<typeof getConversationHistoryLocator>,
  result: ConversationBackgroundRunResult,
  waitForReply: boolean,
) {
  const reply = result.turn.reply;
  return {
    action,
    project_id: projectId,
    session_id: sessionId,
    accepted: true,
    wait_for_reply: waitForReply,
    runtime_status: result.outcome === "error" ? "error" : "idle",
    outcome: result.outcome,
    user_message_id: result.userMessageId,
    ...(result.assistantMessageId
      ? { assistant_message_id: result.assistantMessageId }
      : {}),
    ...(reply ? {
      reply: {
        message_id: reply.message_id,
        role: reply.role,
        content: reply.content,
        status: reply.status,
        provider_id: reply.provider_id,
        model_id: reply.model_id,
        usage: reply.usage ?? null,
        context_tokens: reply.context_tokens ?? null,
        context_tokens_estimated: reply.context_tokens_estimated ?? false,
        ...(reply.content_parts?.length ? { content_parts: reply.content_parts } : {}),
      },
    } : {}),
    history_locator: historyLocator,
  };
}
