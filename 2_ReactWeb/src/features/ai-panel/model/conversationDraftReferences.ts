import type { ConversationDraftReferences } from "../../../entities/llm-chat/model/conversation";

export function emptyConversationDraftReferences(): ConversationDraftReferences {
  return [];
}

export function toConversationDraftReferences(
  references: ConversationDraftReferences,
): ConversationDraftReferences {
  return references.map((item) => {
    if (item.type === "file") return { type: "file", reference: { ...item.reference } };
    if (item.type === "image") return { type: "image", reference: { ...item.reference } };
    return { type: "text", reference: { ...item.reference } };
  });
}

export function fromConversationDraftReferences(
  references: ConversationDraftReferences | undefined,
): ConversationDraftReferences {
  return toConversationDraftReferences(references ?? []);
}

export function areConversationDraftReferencesEqual(
  left: ConversationDraftReferences | undefined,
  right: ConversationDraftReferences | undefined,
) {
  return JSON.stringify(left ?? emptyConversationDraftReferences()) ===
    JSON.stringify(right ?? emptyConversationDraftReferences());
}
