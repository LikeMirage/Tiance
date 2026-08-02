import { fetchNoContent } from "../http/httpClient";

export function deleteToolFolder(toolsetId: string, folderId: string) {
  return fetchNoContent(
    `/api/tools/categories/${encodeURIComponent(toolsetId)}/projects/${encodeURIComponent(folderId)}`,
    { method: "DELETE" },
  );
}
