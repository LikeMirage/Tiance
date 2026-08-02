import type { ProviderModelCheckResult } from "../../entities/llm-provider/model/providerConfig";
import { fetchJson } from "../http/httpClient";

export function checkProviderModel(providerId: string, modelId: string) {
  return fetchJson<ProviderModelCheckResult>(
    `/api/llm/provider-configs/${encodeURIComponent(providerId)}/model-check`,
    {
      method: "POST",
      body: JSON.stringify({
        model_id: modelId,
      }),
    },
  );
}
