import type { DiscoveredModelEntry } from "../../entities/llm-provider/model/discoveredModel";
import { fetchJson } from "../http/httpClient";

export function inferProviderModelMetadata(
  providerId: string,
  input: { model_id: string; display_name: string; family_group: string; capability_tags?: readonly string[] },
) {
  return fetchJson<DiscoveredModelEntry>(
    `/api/llm/provider-configs/${encodeURIComponent(providerId)}/model-metadata`,
    { method: "POST", body: JSON.stringify(input) },
  );
}
