import type { ProviderCatalogOrderResponse } from "../../entities/llm-provider/model/providerCatalog";
import { fetchJson } from "../http/httpClient";

export function getProviderCatalogOrder() {
  return fetchJson<ProviderCatalogOrderResponse>("/api/llm/catalog/providers/order");
}
