import type { ToolFolderListResponse } from "../../entities/tool/model/toolset";
import { fetchJson } from "../http/httpClient";

export function getToolFolders(toolsetId: string) {
  return fetchJson<ToolFolderListResponse>(
    `/api/tools/categories/${encodeURIComponent(toolsetId)}/projects`,
  );
}
