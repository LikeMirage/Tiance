import type {
  ProviderCatalogEntry,
  ProviderCatalogUpdateRequest,
} from "../../entities/llm-provider/model/providerCatalog";
import { fetchJson } from "../http/httpClient";

export function updateProviderCatalogEntry(
  providerId: string,
  input: ProviderCatalogUpdateRequest,
) {
  return fetchJson<ProviderCatalogEntry>(
    `/api/llm/catalog/providers/${providerId}`,
    {
      body: JSON.stringify(input),
      method: "PATCH",
    },
  );
}
