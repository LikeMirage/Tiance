import type {
  ChatCompletionRequest,
  ChatStreamEvent,
} from "../../../entities/llm-chat/model/chatCompletion";
import { HttpRequestError } from "../../../services/http/httpClient";
import { resumeChatCompletionStream } from "../../../services/llm/resumeChatCompletionStream";
import { streamChatCompletion } from "../../../services/llm/streamChatCompletion";
import { isConversationStreamResyncRequired } from "../../../services/llm/conversationStreamErrors";

export type ConversationRunOutcome = "done" | "error" | "cancelled";

export type ConversationRunSettlement = {
  assistantMessageId: string | null;
  outcome: ConversationRunOutcome;
  userMessageId: string;
};

type ConversationRunFollowerDependencies = {
  resume: typeof resumeChatCompletionStream;
  retryDelay: (delayMs: number) => Promise<void>;
  stream: typeof streamChatCompletion;
};

type FollowConversationRunInput = {
  expectedUserMessageId: string;
  initialStrategy?: ConversationRunInitialStrategy;
  onEvent: (event: ChatStreamEvent) => void | Promise<void>;
  onStarted: () => void | Promise<void>;
  request: ChatCompletionRequest;
};

class ConversationRunIdentityMismatchError extends Error {}

export type ConversationRunInitialStrategy = "start" | "resume_then_start";

export async function followConversationRun(
  input: FollowConversationRunInput,
  dependencyOverrides: Partial<ConversationRunFollowerDependencies> = {},
): Promise<ConversationRunSettlement | null> {
  const dependencies: ConversationRunFollowerDependencies = {
    resume: dependencyOverrides.resume ?? resumeChatCompletionStream,
    retryDelay: dependencyOverrides.retryDelay ?? wait,
    stream: dependencyOverrides.stream ?? streamChatCompletion,
  };
  const projectId = input.request.project_id;
  const sessionId = input.request.session_id;
  if (!projectId || !sessionId) {
    throw new Error("会话运行跟随器需要项目和会话标识。");
  }

  let initialConnectionOpened = false;
  let runStarted = false;
  let settlement: ConversationRunSettlement | null = null;

  const handleEvent = async (event: ChatStreamEvent) => {
    if (event.kind === "conversation_resume_reset") return;
    if (event.kind === "conversation_run_started") {
      if (event.user_message_id !== input.expectedUserMessageId) {
        throw new ConversationRunIdentityMismatchError("续接到了另一轮会话运行。");
      }
      if (!runStarted) {
        runStarted = true;
        await input.onStarted();
      }
      return;
    }
    if (event.kind === "conversation_run_settled") {
      if (!runStarted || event.user_message_id !== input.expectedUserMessageId) {
        throw new ConversationRunIdentityMismatchError("会话运行终态不属于本次工具请求。");
      }
      settlement = {
        assistantMessageId: event.assistant_message_id ?? null,
        outcome: event.status,
        userMessageId: event.user_message_id,
      };
      return;
    }
    if (!runStarted) {
      throw new ConversationRunIdentityMismatchError(
        "会话运行尚未通过本次用户消息身份校验。",
      );
    }
    await input.onEvent(event);
  };

  if (input.initialStrategy === "resume_then_start") {
    const resumed = await resumeUntilAvailableOrMissing(
      dependencies,
      projectId,
      sessionId,
      handleEvent,
    );
    if (resumed === "completed") return settlement;
  }

  try {
    await dependencies.stream(input.request, {
      onEvent: handleEvent,
      onOpen: () => {
        initialConnectionOpened = true;
      },
    });
  } catch (error) {
    if (error instanceof ConversationRunIdentityMismatchError) throw error;
    if (!initialConnectionOpened) {
      if (error instanceof HttpRequestError && error.status === 409) {
        const resumed = await resumeUntilAvailableOrMissing(
          dependencies,
          projectId,
          sessionId,
          handleEvent,
        );
        if (resumed === "completed") return settlement;
      }
      throw error;
    }
    if (
      error instanceof HttpRequestError
      && error.status < 500
      && !isConversationStreamResyncRequired(error)
    ) {
      throw error;
    }
  }
  if (settlement) return settlement;

  await resumeUntilAvailableOrMissing(dependencies, projectId, sessionId, handleEvent);
  return settlement;
}

async function resumeUntilAvailableOrMissing(
  dependencies: ConversationRunFollowerDependencies,
  projectId: string,
  sessionId: string,
  handleEvent: (event: ChatStreamEvent) => Promise<void>,
): Promise<"completed" | "missing"> {
  let retryDelayMs = 100;
  while (true) {
    try {
      await dependencies.resume(projectId, sessionId, handleEvent);
      return "completed";
    } catch (error) {
      if (error instanceof ConversationRunIdentityMismatchError) throw error;
      if (error instanceof HttpRequestError) {
        if (error.status === 404) return "missing";
        if (isConversationStreamResyncRequired(error)) {
          await dependencies.retryDelay(retryDelayMs);
          retryDelayMs = Math.min(retryDelayMs * 2, 2_000);
          continue;
        }
        if (error.status < 500) throw error;
      }
      await dependencies.retryDelay(retryDelayMs);
      retryDelayMs = Math.min(retryDelayMs * 2, 2_000);
    }
  }
}

function wait(delayMs: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, delayMs));
}
