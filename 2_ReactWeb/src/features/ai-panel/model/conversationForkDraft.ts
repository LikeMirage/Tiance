import type { ConversationDraftReferences } from "../../../entities/llm-chat/model/conversation";
import type { ChatMessage } from "./chatMessage";
import {
  emptyConversationDraftReferences,
  toConversationDraftReferences,
} from "./conversationDraftReferences";

export type ConversationForkDraft = {
  draft: string;
  references: ConversationDraftReferences;
};

export function buildConversationForkDraft(
  message: ChatMessage,
): ConversationForkDraft {
  const references = message.references ?? emptyConversationDraftReferences();
  return {
    draft: message.content,
    references: toConversationDraftReferences(references),
  };
}
