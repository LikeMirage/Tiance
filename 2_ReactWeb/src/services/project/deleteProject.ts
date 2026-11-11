import { fetchNoContent } from "../http/httpClient";

export type DeleteProjectOptions = {
  deleteFiles?: boolean;
  clearTianceData?: boolean;
};

export function deleteProject(projectId: string, options: DeleteProjectOptions = {}) {
  const params = new URLSearchParams();
  if (options.deleteFiles) params.set("delete_files", "true");
  if (options.clearTianceData) params.set("clear_tiance_data", "true");
  const query = params.size ? `?${params}` : "";
  return fetchNoContent(`/api/projects/${encodeURIComponent(projectId)}${query}`, {
    method: "DELETE",
  });
}
