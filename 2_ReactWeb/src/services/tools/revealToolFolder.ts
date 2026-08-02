import { fetchNoContent } from "../http/httpClient";

export function revealToolFolder(toolsetId: string, folderId: string) {
  return fetchNoContent(
    `/api/tools/categories/${encodeURIComponent(toolsetId)}/projects/${encodeURIComponent(folderId)}/reveal`,
    { method: "POST" },
  );
}
