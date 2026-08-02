import type { ProjectFileNode } from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";
import { readFileAsBase64 } from "./readFileAsBase64";

export type ProjectUserFileUploadResponse = {
  project_id: string;
  path: string;
  original_filename: string;
  mime_type: string | null;
  size_bytes: number;
  node: ProjectFileNode;
};

export async function uploadProjectUserFile(
  projectId: string,
  file: File,
  options?: Pick<RequestInit, "signal">,
): Promise<ProjectUserFileUploadResponse> {
  const dataBase64 = await readFileAsBase64(file);
  return fetchJson<ProjectUserFileUploadResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/uploads/files`,
    {
      method: "POST",
      body: JSON.stringify({
        filename: file.name || "uploaded_file",
        mime_type: file.type || null,
        data_base64: dataBase64,
      }),
      signal: options?.signal,
    },
  );
}
