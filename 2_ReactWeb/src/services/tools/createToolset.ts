import type {
  Toolset,
  ToolsetCreateRequest,
} from "../../entities/tool/model/toolset";
import { fetchJson } from "../http/httpClient";

export function createToolset(payload: ToolsetCreateRequest = {}) {
  return fetchJson<Toolset>("/api/tools/categories", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
