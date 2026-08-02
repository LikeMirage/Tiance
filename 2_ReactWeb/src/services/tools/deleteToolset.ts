import { fetchNoContent } from "../http/httpClient";

export function deleteToolset(toolsetId: string) {
  return fetchNoContent(`/api/tools/categories/${encodeURIComponent(toolsetId)}`, {
    method: "DELETE",
  });
}
