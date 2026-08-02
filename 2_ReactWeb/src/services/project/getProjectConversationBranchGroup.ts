import type { ConversationBranchGroupDetailResponse } from "../../entities/llm-chat/model/conversation";
import { fetchJson } from "../http/httpClient";

export function getProjectConversationBranchGroup(
  projectId: string,
  groupId: string,
  signal?: AbortSignal,
) {
  return fetchJson<ConversationBranchGroupDetailResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/conversation-branches/${encodeURIComponent(groupId)}`,
    { signal },
  );
}
