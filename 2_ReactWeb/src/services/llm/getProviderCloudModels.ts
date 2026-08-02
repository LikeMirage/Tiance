import type { ProviderCloudModelCacheResponse } from "../../entities/llm-provider/model/discoveredModel";
import { fetchJson } from "../http/httpClient";

export function getProviderCloudModels(providerId: string) {
  return fetchJson<ProviderCloudModelCacheResponse>(
    `/api/llm/provider-configs/${providerId}/cloud-models`,
  );
}
