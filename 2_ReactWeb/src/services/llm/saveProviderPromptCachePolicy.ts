import type { ProviderPromptCachePolicyResponse } from "../../entities/llm-provider/model/providerConfig";
import { fetchJson } from "../http/httpClient";

export function saveProviderPromptCachePolicy(
  providerId: string,
  promptCacheRetentionSeconds: number,
) {
  return fetchJson<ProviderPromptCachePolicyResponse>(
    `/api/llm/provider-configs/${providerId}/prompt-cache-policy`,
    {
      body: JSON.stringify({
        prompt_cache_retention_seconds: promptCacheRetentionSeconds,
      }),
      method: "PUT",
    },
  );
}
