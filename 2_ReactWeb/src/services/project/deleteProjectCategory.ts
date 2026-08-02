import { fetchNoContent } from "../http/httpClient";

export function deleteProjectCategory(categoryId: string) {
  return fetchNoContent(`/api/projects/categories/${encodeURIComponent(categoryId)}`, {
    method: "DELETE",
  });
}
