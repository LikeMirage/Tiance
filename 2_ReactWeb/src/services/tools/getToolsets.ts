import type { ToolsetListResponse } from "../../entities/tool/model/toolset";
import { fetchJson } from "../http/httpClient";

export function getToolsets() {
  return fetchJson<ToolsetListResponse>("/api/tools/categories");
}
