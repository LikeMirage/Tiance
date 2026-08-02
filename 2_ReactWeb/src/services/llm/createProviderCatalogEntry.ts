import type {
  ProviderCatalogCreateRequest,
  ProviderCatalogEntry,
} from "../../entities/llm-provider/model/providerCatalog";
import { fetchJson } from "../http/httpClient";

export function createProviderCatalogEntry(input: ProviderCatalogCreateRequest) {
  return fetchJson<ProviderCatalogEntry>("/api/llm/catalog/providers", {
    body: JSON.stringify(input),
    method: "POST",
  });
}
