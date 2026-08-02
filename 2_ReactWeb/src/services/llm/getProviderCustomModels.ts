import type { ProviderCustomModelListResponse } from "../../entities/llm-provider/model/providerCustomModel";
import { fetchJson } from "../http/httpClient";

export function getProviderCustomModels(providerId: string) {
  return fetchJson<ProviderCustomModelListResponse>(
    `/api/llm/provider-configs/${encodeURIComponent(providerId)}/custom-models`,
  );
}
