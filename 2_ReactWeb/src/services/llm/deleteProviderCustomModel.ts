import { fetchNoContent } from "../http/httpClient";

export function deleteProviderCustomModel(
  providerId: string,
  modelId: string,
) {
  return fetchNoContent(
    `/api/llm/provider-configs/${encodeURIComponent(providerId)}/custom-models/${encodeURIComponent(modelId)}`,
    {
      method: "DELETE",
    },
  );
}
