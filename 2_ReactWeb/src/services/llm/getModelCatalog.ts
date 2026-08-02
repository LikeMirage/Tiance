import type {
  LlmModelCatalogKind,
  LlmModelCatalogListResponse,
} from "../../entities/llm-provider/model/modelCatalog";
import { fetchJson } from "../http/httpClient";

type GetModelCatalogOptions = {
  enabledOnly?: boolean;
  kind?: LlmModelCatalogKind;
};

export function getModelCatalog(options: GetModelCatalogOptions = {}) {
  const params = new URLSearchParams();
  if (options.enabledOnly === false) {
    params.set("enabled_only", "false");
  }
  if (options.kind) {
    params.set("kind", options.kind);
  }

  const query = params.toString();
  return fetchJson<LlmModelCatalogListResponse>(
    `/api/llm/models${query ? `?${query}` : ""}`,
  );
}
