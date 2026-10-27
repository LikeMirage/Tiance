import { revealInFileExplorer } from "../desktop/fileExplorer";

export function revealProviderCatalogEntry(providerId: string) {
  return revealInFileExplorer(
    `/api/llm/catalog/providers/${encodeURIComponent(providerId)}/reveal`,
    { method: "POST" },
  );
}
