import { fetchJson } from "../http/httpClient";

export async function claimClientToolRequest(requestId: string): Promise<boolean> {
  const response = await fetchJson<{ acquired: boolean }>(
    `/api/llm/client-tools/${encodeURIComponent(requestId)}/claim`,
    { method: "POST" },
  );
  return response.acquired;
}
