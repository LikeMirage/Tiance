import type { ToolFolder } from "../../entities/tool/model/toolset";
import { fetchJson } from "../http/httpClient";

export function moveToolFolderToToolset(
  toolsetId: string,
  folderId: string,
  targetToolsetId: string,
) {
  return fetchJson<ToolFolder>(
    `/api/tools/categories/${encodeURIComponent(toolsetId)}/projects/${encodeURIComponent(folderId)}/category`,
    {
      method: "PATCH",
      body: JSON.stringify({ target_category_id: targetToolsetId }),
    },
  );
}
