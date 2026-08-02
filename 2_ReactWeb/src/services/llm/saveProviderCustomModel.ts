import type {
  ProviderCustomModelEntry,
  ProviderCustomModelSaveRequest,
} from "../../entities/llm-provider/model/providerCustomModel";
import { fetchJson } from "../http/httpClient";

export function saveProviderCustomModel(
  providerId: string,
  input: ProviderCustomModelSaveRequest,
) {
  return fetchJson<ProviderCustomModelEntry>(
    `/api/llm/provider-configs/${encodeURIComponent(providerId)}/custom-models`,
    {
      body: JSON.stringify({
        capability_tags: input.capability_tags,
        cache_hit_price_per_million: input.cache_hit_price_per_million,
        display_name: input.display_name,
        family_group: input.family_group,
        input_price_per_million: input.input_price_per_million,
        model_id: input.model_id,
        note: input.note,
        output_price_per_million: input.output_price_per_million,
        price_currency: input.price_currency,
      }),
      method: "POST",
    },
  );
}
