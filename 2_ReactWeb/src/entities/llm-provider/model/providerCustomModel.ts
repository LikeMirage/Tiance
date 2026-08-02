export interface ProviderCustomModelEntry {
  provider_id: string;
  model_id: string;
  display_name: string;
  family_group: string;
  capability_tags: string[];
  note: string;
  price_currency: string;
  input_price_per_million: number | null;
  cache_hit_price_per_million: number | null;
  output_price_per_million: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProviderCustomModelListResponse {
  count: number;
  items: ProviderCustomModelEntry[];
}

export interface ProviderCustomModelSaveRequest {
  model_id: string;
  display_name: string;
  family_group: string;
  capability_tags: string[];
  note: string;
  price_currency: string;
  input_price_per_million: number | null;
  cache_hit_price_per_million: number | null;
  output_price_per_million: number | null;
}
