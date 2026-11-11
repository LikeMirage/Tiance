import { fetchJson } from "../http/httpClient";

export function initializeProjectFiles(
  projectId: string, projectKind: "tool" | "role" | "theme",
  files: readonly { path: string; content: string }[],
) {
  // Await mutation settlement even when the caller disconnects. A retry never overwrites files.
  return fetchJson<{ project_id: string; root_path: string; written_files: string[]; preserved_files: string[] }>(
    `/api/projects/${encodeURIComponent(projectId)}/files/scaffold`,
    { method: "POST", body: JSON.stringify({ project_kind: projectKind, files }) },
  );
}
