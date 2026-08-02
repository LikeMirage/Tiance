import type {
  ConversationMessage,
  ConversationMessageTurnResponse,
} from "../../../entities/llm-chat/model/conversation";
import { getProjectConversationMessageTurn } from "../../../services/project/getProjectConversationMessageTurn";
import { getProjectConversationMessages } from "../../../services/project/getProjectConversationMessages";
import {
  toConversationTurn,
  type CompletedConversationTurn,
  type ConversationTurn,
} from "./conversationMessageTurns";
import {
  iterateBackwardConversationMessagePages,
  type ConversationMessagePageLoader,
} from "./conversationMessagePagination";

// This only controls transport batch size. There is deliberately no total
// history ceiling: collectors continue until their semantic stop condition.
const MESSAGE_PAGE_SIZE = 1_000;

export async function loadRecentCompletedConversationTurns(
  projectId: string,
  sessionId: string,
  depth: number,
) {
  return collectRecentCompletedConversationTurns(
    createMessagePageLoader(projectId, sessionId),
    depth,
  );
}

export async function collectRecentCompletedConversationTurns(
  loadPage: ConversationMessagePageLoader,
  depth: number,
): Promise<{
  historyExhausted: boolean;
  loadedMessageCount: number;
  totalMessageCount: number | null;
  turns: CompletedConversationTurn[];
}> {
  if (!Number.isInteger(depth) || depth <= 0) {
    throw new Error("已完成轮次读取深度必须是正整数。");
  }

  const turnsNewestFirst: CompletedConversationTurn[] = [];
  let trailingMessagesNewestFirst: ConversationMessage[] = [];
  let loadedMessageCount = 0;
  let totalMessageCount: number | null = null;

  for await (const page of iterateBackwardConversationMessagePages(loadPage)) {
    loadedMessageCount += page.items.length;
    totalMessageCount = page.total_count ?? totalMessageCount;

    for (let index = page.items.length - 1; index >= 0; index -= 1) {
      const message = page.items[index];
      if (message.role !== "user") {
        trailingMessagesNewestFirst.push(message);
        continue;
      }

      const turn = toCompletedTurnFromBackwardMessages(
        message,
        trailingMessagesNewestFirst,
      );
      if (turn) turnsNewestFirst.push(turn);
      trailingMessagesNewestFirst = [];
    }

    if (turnsNewestFirst.length >= depth || !page.has_more) {
      return {
        historyExhausted: !page.has_more,
        loadedMessageCount,
        totalMessageCount,
        turns: turnsNewestFirst.slice(0, depth).reverse(),
      };
    }
  }

  throw new Error("会话消息分页意外结束。");
}

export async function loadConversationTurnByUserMessageId(
  projectId: string,
  sessionId: string,
  userMessageId: string,
): Promise<ConversationTurn> {
  if (!userMessageId.trim()) {
    throw new Error("user_message_id 不能为空。");
  }
  const response = await getProjectConversationMessageTurn(
    projectId,
    sessionId,
    userMessageId,
  );
  return parseConversationMessageTurn(response, {
    projectId,
    sessionId,
    userMessageId,
  });
}

export function parseConversationMessageTurn(
  response: ConversationMessageTurnResponse,
  expected: {
    projectId: string;
    sessionId: string;
    userMessageId: string;
  },
): ConversationTurn {
  if (
    response.project_id !== expected.projectId
    || response.session_id !== expected.sessionId
    || response.user_message_id !== expected.userMessageId
  ) {
    throw new Error("精确轮次响应与请求的会话身份不一致。");
  }
  if (response.count !== response.items.length) {
    throw new Error("精确轮次响应的消息数量不一致。");
  }
  const firstMessage = response.items[0];
  if (
    !firstMessage
    || firstMessage.role !== "user"
    || firstMessage.message_id !== expected.userMessageId
  ) {
    throw new Error("精确轮次响应缺少目标用户消息。");
  }
  for (let index = 1; index < response.items.length; index += 1) {
    if (response.items[index].role === "user") {
      throw new Error("精确轮次响应包含下一轮用户消息。");
    }
  }
  const turn = toConversationTurn(response.items);
  if (!turn) throw new Error("无法解析目标用户消息所属轮次。");
  return turn;
}

function createMessagePageLoader(
  projectId: string,
  sessionId: string,
): ConversationMessagePageLoader {
  return (beforeMessageId) => getProjectConversationMessages(projectId, sessionId, {
    beforeMessageId,
    limit: MESSAGE_PAGE_SIZE,
  });
}

function toCompletedTurnFromBackwardMessages(
  user: ConversationMessage,
  trailingMessagesNewestFirst: readonly ConversationMessage[],
): CompletedConversationTurn | null {
  const turn = toConversationTurn([
    user,
    ...trailingMessagesNewestFirst.slice().reverse(),
  ]);
  if (!turn || !turn.reply) return null;
  if (turn.messages.some((message) => message.status === "running")) return null;
  if (turn.reply.status !== "done" && turn.reply.status !== "error") return null;
  return {
    messages: turn.messages,
    reply: turn.reply,
    user: turn.user,
  };
}
