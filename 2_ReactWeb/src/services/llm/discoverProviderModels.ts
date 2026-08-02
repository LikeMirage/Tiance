import type { DiscoveredModelListResponse } from "../../entities/llm-provider/model/discoveredModel";
import { fetchJson } from "../http/httpClient";

type DiscoverProviderModelsInput = {
  apiBaseUrl: string;
  modelDiscoveryUrl?: string;
  apiKey: string;
  providerId: string;
};

export function discoverProviderModels(input: DiscoverProviderModelsInput) {
  return fetchJson<DiscoveredModelListResponse>(
    `/api/llm/catalog/providers/${input.providerId}/discover-models`,
    {
      body: JSON.stringify({
        api_base_url: input.apiBaseUrl,
        model_discovery_url: input.modelDiscoveryUrl || null,
        api_key: input.apiKey,
      }),
      method: "POST",
    },
  );
}
