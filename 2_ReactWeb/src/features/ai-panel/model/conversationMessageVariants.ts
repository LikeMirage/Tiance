import type {
  ConversationMessageVariant,
  ConversationSession,
} from "../../../entities/llm-chat/model/conversation";
import type { ChatMessage } from "./chatMessage";

export type MessageVariantTarget = {
  messageId: string;
  position: number;
  sessionId: string;
};

export type MessageVariantNavigation = {
  count: number;
  currentPosition: number;
  next: MessageVariantTarget;
  previous: MessageVariantTarget;
};

export function resolveMessageVariantNavigation(
  message: ChatMessage,
  variants: ConversationMessageVariant[],
  sessions: ConversationSession[],
  activeSessionId?: string | null,
): MessageVariantNavigation | null {
  if (message.role !== "user" || !message.variantGroupId) return null;
  const liveSessionIds = new Set(sessions.map((session) => session.session_id));
  const currentOriginMessageId = message.originMessageId ?? message.id;
  const eligibleVariants = variants
    .filter((variant) => variant.variant_group_id === message.variantGroupId)
    .map((variant) => (
      variant.origin_message_id === currentOriginMessageId && variant.deleted_at && activeSessionId
        ? { ...variant, deleted_at: null, session_id: activeSessionId, message_id: message.id }
        : variant
    ))
    .filter((variant) => (
      !variant.deleted_at && Boolean(variant.message_id) && liveSessionIds.has(variant.session_id)
    ));
  const group = [...new Map(
    eligibleVariants.map((variant) => [variant.origin_message_id, variant]),
  ).values()]
    .sort((left, right) => left.variant_index - right.variant_index);
  if (group.length < 2) return null;
  const currentIndex = group.findIndex((variant) => (
    variant.origin_message_id === currentOriginMessageId
  ));
  if (currentIndex < 0) return null;
  return {
    count: group.length,
    currentPosition: currentIndex + 1,
    previous: targetFromVariant(group[(currentIndex - 1 + group.length) % group.length], currentIndex),
    next: targetFromVariant(group[(currentIndex + 1) % group.length], currentIndex + 2),
  };
}

function targetFromVariant(
  variant: ConversationMessageVariant,
  fallbackPosition: number,
): MessageVariantTarget {
  return {
    messageId: variant.message_id ?? "",
    position: variant.variant_index || fallbackPosition,
    sessionId: variant.session_id,
  };
}
