import { fetchNoContent } from "../http/httpClient";

export function deleteProviderCatalogEntry(providerId: string) {
  return fetchNoContent(
    `/api/llm/catalog/providers/${encodeURIComponent(providerId)}`,
    {
      method: "DELETE",
    },
  );
}
