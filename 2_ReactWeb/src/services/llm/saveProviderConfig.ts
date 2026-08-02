import type {
  ProviderConfig,
  ProviderConfigSaveRequest,
} from "../../entities/llm-provider/model/providerConfig";
import { fetchJson } from "../http/httpClient";

export function saveProviderConfig(
  providerId: string,
  input: ProviderConfigSaveRequest,
) {
  return fetchJson<ProviderConfig>(`/api/llm/provider-configs/${providerId}`, {
    body: JSON.stringify({
      api_base_url: input.api_base_url,
      protocol_family: input.protocol_family,
      auth_scheme: input.auth_scheme,
      model_discovery_url: input.model_discovery_url,
      model_discovery_strategy: input.model_discovery_strategy,
      model_discovery_auth_scheme: input.model_discovery_auth_scheme,
      api_keys: input.api_keys,
      enabled: input.enabled,
    }),
    method: "PUT",
  });
}
