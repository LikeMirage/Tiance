import { fetchJson } from "../http/httpClient";

export async function renewClientToolClaim(
  requestId: string,
  ownership: { executorId: string; claimId: string },
): Promise<boolean> {
  const response = await fetchJson<{ renewed: boolean }>(
    `/api/llm/client-tools/${encodeURIComponent(requestId)}/lease`,
    {
      method: "POST",
      body: JSON.stringify({
        executor_id: ownership.executorId,
        claim_id: ownership.claimId,
      }),
    },
  );
  return response.renewed;
}
