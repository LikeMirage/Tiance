import { fetchJson } from "../http/httpClient";

export type ToolPermissionDecisionAck = {
  accepted: boolean;
};

export async function submitToolPermissionDecision(
  requestId: string,
  decision: "allow" | "deny",
): Promise<ToolPermissionDecisionAck> {
  return fetchJson<ToolPermissionDecisionAck>(
    `/api/llm/tool-permissions/${encodeURIComponent(requestId)}/decision`,
    {
      method: "POST",
      body: JSON.stringify({ decision }),
    },
  );
}
