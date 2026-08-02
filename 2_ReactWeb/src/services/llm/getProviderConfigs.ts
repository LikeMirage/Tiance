import type { ProviderConfigListResponse } from "../../entities/llm-provider/model/providerConfig";
import { fetchJson } from "../http/httpClient";

export function getProviderConfigs() {
  return fetchJson<ProviderConfigListResponse>("/api/llm/provider-configs");
}
