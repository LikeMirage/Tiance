import type { ProviderCatalogResponse } from "../../entities/llm-provider/model/providerCatalog";
import { fetchJson } from "../http/httpClient";

export function getProviderCatalog() {
  return fetchJson<ProviderCatalogResponse>("/api/llm/catalog/providers");
}
