import { fetchJson } from "../http/httpClient";
import type { ClientToolExecutionResult } from "../../features/client-tools/model/clientToolBridge";

export type ClientToolResultAck = {
  accepted: boolean;
};

export async function submitClientToolResult(
  requestId: string,
  result: ClientToolExecutionResult,
): Promise<ClientToolResultAck> {
  const response = await fetchJson<ClientToolResultAck>(`/api/llm/client-tools/${encodeURIComponent(requestId)}/result`, {
    method: "POST",
    body: JSON.stringify({
      ok: result.ok,
      content: result.content ?? null,
      error: result.error ?? null,
    }),
  });
  return response;
}
