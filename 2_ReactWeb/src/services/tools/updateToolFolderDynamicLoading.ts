import type {
  ToolFolderDynamicLoadingRequest,
  ToolFolderDynamicLoadingResponse,
} from "../../entities/tool/model/toolset";
import { fetchJson } from "../http/httpClient";

export function updateToolFolderDynamicLoading(
  toolsetId: string,
  folderId: string,
  payload: ToolFolderDynamicLoadingRequest,
) {
  return fetchJson<ToolFolderDynamicLoadingResponse>(
    `/api/tools/categories/${encodeURIComponent(toolsetId)}/projects/${encodeURIComponent(folderId)}/dynamic-loading`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}
