import type { ProjectFileNode } from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";
import { readFileAsBase64 } from "./readFileAsBase64";

export type ProjectImageUploadResponse = {
  project_id: string;
  path: string;
  mime_type: string;
  size_bytes: number;
  node: ProjectFileNode;
};

export async function uploadProjectPastedImage(
  projectId: string,
  file: File,
  options?: Pick<RequestInit, "signal">,
): Promise<ProjectImageUploadResponse> {
  if (!file.type.startsWith("image/")) {
    throw new Error("只能保存图片文件。");
  }
  const dataBase64 = await readFileAsBase64(file);
  return fetchJson<ProjectImageUploadResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/uploads/images`,
    {
      method: "POST",
      body: JSON.stringify({
        filename: file.name || null,
        mime_type: file.type,
        data_base64: dataBase64,
      }),
      signal: options?.signal,
    },
  );
}
