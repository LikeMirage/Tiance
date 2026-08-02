import type {
  ProviderCatalogOrderResponse,
  ProviderCatalogOrderSaveRequest,
} from "../../entities/llm-provider/model/providerCatalog";
import { fetchJson } from "../http/httpClient";

export function saveProviderCatalogOrder(input: ProviderCatalogOrderSaveRequest) {
  return fetchJson<ProviderCatalogOrderResponse>("/api/llm/catalog/providers/order", {
    body: JSON.stringify({
      provider_ids: input.provider_ids,
    }),
    method: "PUT",
  });
}
