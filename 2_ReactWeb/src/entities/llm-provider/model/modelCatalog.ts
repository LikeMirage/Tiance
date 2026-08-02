export type LlmModelCatalogKind = "chat" | "functional_text" | "vision";

export interface LlmModelCatalogEntry {
  provider_id: string;
  provider_label: string;
  provider_enabled: boolean;
  protocol_family: string;
  model_id: string;
  model_label: string;
  family_group: string;
  capability_tags: string[];
  source: string;
  price_currency: string;
  input_price_per_million: number | null;
  cache_hit_price_per_million: number | null;
  output_price_per_million: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface LlmModelCatalogListResponse {
  count: number;
  items: LlmModelCatalogEntry[];
}
