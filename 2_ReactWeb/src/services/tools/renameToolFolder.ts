import type { ToolFolder } from "../../entities/tool/model/toolset";
import { fetchJson } from "../http/httpClient";

export function renameToolFolder(
  toolsetId: string,
  folderId: string,
  name: string,
) {
  return fetchJson<ToolFolder>(
    `/api/tools/categories/${encodeURIComponent(toolsetId)}/projects/${encodeURIComponent(folderId)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ name }),
    },
  );
}
