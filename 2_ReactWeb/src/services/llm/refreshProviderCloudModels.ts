import type { ProviderCloudModelCacheResponse } from "../../entities/llm-provider/model/discoveredModel";
import { fetchJson } from "../http/httpClient";

export function refreshProviderCloudModels(providerId: string) {
  return fetchJson<ProviderCloudModelCacheResponse>(
    `/api/llm/provider-configs/${providerId}/cloud-models/refresh`,
    {
      method: "POST",
    },
  );
}
