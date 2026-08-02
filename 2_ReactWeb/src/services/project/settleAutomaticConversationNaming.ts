import { fetchJson } from "../http/httpClient";

export type SettleAutomaticConversationNamingResult = {
  task_id: string;
  status: "completed" | "superseded" | "failed";
};

export function settleAutomaticConversationNaming(
  projectId: string,
  functionSessionId: string,
  outcome: "done" | "error" | "cancelled",
) {
  return fetchJson<SettleAutomaticConversationNamingResult>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/`
      + `${encodeURIComponent(functionSessionId)}/automatic-naming/settle`,
    {
      method: "POST",
      body: JSON.stringify({ outcome }),
    },
  );
}
