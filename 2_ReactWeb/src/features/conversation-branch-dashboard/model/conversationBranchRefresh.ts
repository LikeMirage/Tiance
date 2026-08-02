import type { ConversationBranchGroup } from "../../../entities/llm-chat/model/conversation";
import type { ProjectConversationUpdatedDetail } from "../../../entities/llm-chat/model/projectConversationEvents";

export function shouldAutoRefreshConversationBranchDashboard(
  event: ProjectConversationUpdatedDetail,
  projectId: string | null,
) {
  return event.projectId === projectId && (
    event.kind === "content" || event.kind === "structure"
  );
}

export function findActiveConversationBranchGroupId(
  groups: readonly ConversationBranchGroup[],
  activeSessionId: string | null,
) {
  if (!activeSessionId) return null;
  return groups.find((group) => group.session_ids.includes(activeSessionId))?.group_id ?? null;
}
