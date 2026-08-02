import { fetchJson } from "../http/httpClient";

export type ApplyAutomaticConversationTitleResult = {
  applied: boolean;
  source_session_id: string;
  status: "completed" | "superseded";
  title: string;
};

export function applyAutomaticConversationTitle(
  projectId: string,
  functionSessionId: string,
  input: {
    title: string;
  },
) {
  return fetchJson<ApplyAutomaticConversationTitleResult>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/`
      + `${encodeURIComponent(functionSessionId)}/automatic-title`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}
