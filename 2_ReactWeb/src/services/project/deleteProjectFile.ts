import { fetchNoContent } from "../http/httpClient";

export function deleteProjectFile(projectId: string, path: string) {
  return fetchNoContent(
    `/api/projects/${encodeURIComponent(projectId)}/files?path=${encodeURIComponent(path)}`,
    {
      method: "DELETE",
    },
  );
}
