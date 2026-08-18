import type {
  ToolFolderRuntimeSettingsRequest,
  ToolFolderRuntimeSettingsResponse,
} from "../../entities/tool/model/toolset";
import { fetchJson } from "../http/httpClient";

export function updateToolFolderRuntimeSettings(
  toolsetId: string,
  folderId: string,
  payload: ToolFolderRuntimeSettingsRequest,
) {
  return fetchJson<ToolFolderRuntimeSettingsResponse>(
    `/api/tools/categories/${encodeURIComponent(toolsetId)}/projects/${encodeURIComponent(folderId)}/runtime-settings`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}
