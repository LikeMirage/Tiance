import { fetchNoContent } from "../http/httpClient";

export function revealProviderCatalogEntry(providerId: string) {
  return fetchNoContent(
    `/api/llm/catalog/providers/${encodeURIComponent(providerId)}/reveal`,
    { method: "POST" },
  );
}
