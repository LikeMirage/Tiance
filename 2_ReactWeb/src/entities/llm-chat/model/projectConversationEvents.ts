import type { ChatUsage } from "./chatCompletion";
import type { ConversationRuntimeStatus } from "./conversation";

const PROJECT_CONVERSATION_EVENT = "tiance:project-conversation-updated";

export type ProjectConversationChangeKind =
  | "content"
  | "runtime"
  | "selection"
  | "structure"
  | "usage";

export type ProjectConversationUpdatedDetail = {
  kind: ProjectConversationChangeKind;
  projectId: string;
  runtimeStatus?: ConversationRuntimeStatus;
  sessionId?: string;
  usage?: ChatUsage;
};

export function dispatchProjectConversationUpdated(
  detail: ProjectConversationUpdatedDetail,
) {
  window.dispatchEvent(
    new CustomEvent<ProjectConversationUpdatedDetail>(
      PROJECT_CONVERSATION_EVENT,
      { detail },
    ),
  );
}

export function listenProjectConversationUpdated(
  listener: (detail: ProjectConversationUpdatedDetail) => void,
) {
  const handler = (event: Event) => {
    listener((event as CustomEvent<ProjectConversationUpdatedDetail>).detail);
  };
  window.addEventListener(PROJECT_CONVERSATION_EVENT, handler);
  return () => window.removeEventListener(PROJECT_CONVERSATION_EVENT, handler);
}
