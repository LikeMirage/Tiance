import { fetchNoContent } from "../http/httpClient";

export type DeleteProjectOptions = {
  deleteFiles?: boolean;
};

export function deleteProject(projectId: string, options: DeleteProjectOptions = {}) {
  const query = options.deleteFiles ? "?delete_files=true" : "";
  return fetchNoContent(`/api/projects/${encodeURIComponent(projectId)}${query}`, {
    method: "DELETE",
  });
}
