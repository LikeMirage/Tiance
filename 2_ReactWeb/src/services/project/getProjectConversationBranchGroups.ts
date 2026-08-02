import type { ConversationBranchGroupListResponse } from "../../entities/llm-chat/model/conversation";
import { fetchJson } from "../http/httpClient";

export function getProjectConversationBranchGroups(
  projectId: string,
  signal?: AbortSignal,
) {
  return fetchJson<ConversationBranchGroupListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/conversation-branches`,
    { signal },
  );
}
