import type { DiscoveredModelListResponse } from "../../entities/llm-provider/model/discoveredModel";
import { fetchJson } from "../http/httpClient";

export function discoverSavedProviderConfigModels(providerId: string) {
  return fetchJson<DiscoveredModelListResponse>(
    `/api/llm/provider-configs/${providerId}/discover-models`,
    {
      method: "POST",
    },
  );
}
