import { fetchJson } from "../http/httpClient";

export type ClientToolClaimLease = {
  acquired: boolean;
  claim_id: string | null;
  lease_duration_seconds: number | null;
  resumed: boolean;
  attempt_id?: string | null;
};

export async function claimClientToolRequest(
  requestId: string,
  executorId: string,
  options?: { attemptId: string; signal: AbortSignal },
): Promise<ClientToolClaimLease> {
  return fetchJson<ClientToolClaimLease>(
    `/api/llm/client-tools/${encodeURIComponent(requestId)}/claim`,
    {
      method: "POST",
      body: JSON.stringify({ executor_id: executorId, attempt_id: options?.attemptId }),
      signal: options?.signal,
    },
  );
}
