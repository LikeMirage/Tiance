import type { ProviderModelUsageSummaryResponse } from "../../entities/llm-usage/model/providerModelUsage";
import { fetchJson } from "../http/httpClient";

export function getProviderModelUsageSummary(
  providerId?: string | null,
  init?: Pick<RequestInit, "signal">,
) {
  const query = providerId ? `?provider_id=${encodeURIComponent(providerId)}` : "";
  return fetchJson<ProviderModelUsageSummaryResponse>(
    `/api/llm/usage/provider-model-summary${query}`,
    { cache: "no-store", signal: init?.signal },
  );
}
