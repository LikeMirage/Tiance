import type { ConversationMessage } from "../../../entities/llm-chat/model/conversation";

export type CompletedConversationTurn = {
  messages: ConversationMessage[];
  reply: ConversationMessage;
  user: ConversationMessage;
};

export type ConversationTurn = {
  messages: ConversationMessage[];
  reply: ConversationMessage | null;
  user: ConversationMessage;
};

export type ConversationMessageFormat = "content_only" | "full";

export function serializeConversationTurns(
  turns: readonly CompletedConversationTurn[],
  format: ConversationMessageFormat,
) {
  if (format === "full") {
    return turns.map((turn) => ({
      user_message_id: turn.user.message_id,
      reply_message_id: turn.reply.message_id,
      messages: turn.messages,
    }));
  }
  return turns.map((turn) => ({
    user: toContentOnlyMessage(turn.user),
    reply: toContentOnlyMessage(turn.reply),
  }));
}

export function toConversationTurn(
  messages: readonly ConversationMessage[],
): ConversationTurn | null {
  const user = messages[0];
  if (!user || user.role !== "user") return null;

  let lastToolIndex = -1;
  let replyIndex = -1;
  for (let index = 1; index < messages.length; index += 1) {
    const message = messages[index];
    if (message.role === "tool") lastToolIndex = index;
    if (
      (message.role === "assistant" || message.role === "error")
      && (message.status === "done" || message.status === "error" || message.status === "cancelled")
    ) {
      replyIndex = index;
    }
  }

  let reply = replyIndex >= lastToolIndex && replyIndex >= 0 ? messages[replyIndex] : null;
  if (reply?.role === "assistant" && reply.tool_calls?.length && replyIndex === messages.length - 1) {
    reply = null;
  }
  return {
    messages: [...messages],
    reply,
    user,
  };
}

function toContentOnlyMessage(message: ConversationMessage) {
  return {
    message_id: message.message_id,
    role: message.role,
    content: message.content,
    ...(message.content_parts?.length ? { content_parts: message.content_parts } : {}),
  };
}
