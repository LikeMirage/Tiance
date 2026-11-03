import type { ConversationDraftReferences } from "../../../entities/llm-chat/model/conversation";

type DraftInput = { draft: string; references: ConversationDraftReferences };

/** Return a rejected submission to its draft without losing newer typing or refs. */
export function recoverConversationDraft(current: DraftInput, rejected: DraftInput): DraftInput {
  const referenceIds = new Set(current.references.map((item) => `${item.type}:${item.reference.id}`));
  return {
    draft: !current.draft || current.draft === rejected.draft
      ? rejected.draft
      : !rejected.draft ? current.draft : `${rejected.draft}\n\n${current.draft}`,
    references: [
      ...rejected.references.filter((item) => !referenceIds.has(`${item.type}:${item.reference.id}`)),
      ...current.references,
    ],
  };
}
