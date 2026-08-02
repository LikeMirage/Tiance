import type { Toolset } from "../../entities/tool/model/toolset";
import { fetchJson } from "../http/httpClient";

export function renameToolset(toolsetId: string, name: string) {
  return fetchJson<Toolset>(`/api/tools/categories/${encodeURIComponent(toolsetId)}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}
