import type {
  ToolFolder,
  ToolFolderCreateRequest,
} from "../../entities/tool/model/toolset";
import { fetchJson } from "../http/httpClient";

export function createToolFolder(
  toolsetId: string,
  payload: ToolFolderCreateRequest = {},
) {
  return fetchJson<ToolFolder>(
    `/api/tools/categories/${encodeURIComponent(toolsetId)}/projects`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}
