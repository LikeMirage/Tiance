export type ProviderModelUsageSummary = {
  provider_id: string | null;
  provider_display_name: string | null;
  model_id: string | null;
  usage_feature_key?: string | null;
  usage_feature_display_name?: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  reasoning_tokens: number;
  prompt_cache_hit_tokens: number;
  prompt_cache_miss_tokens: number;
  cost_amount?: number | null;
  cost_currency?: string | null;
  record_count: number;
  estimated_record_count: number;
  by_features?: ProviderModelUsageSummary[];
};

export type ProviderUsageSummary = {
  provider_id: string;
  provider_display_name: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  reasoning_tokens: number;
  prompt_cache_hit_tokens: number;
  prompt_cache_miss_tokens: number;
  cost_amount?: number | null;
  cost_currency?: string | null;
  record_count: number;
  estimated_record_count: number;
  by_models: ProviderModelUsageSummary[];
};

export type ProviderModelUsageSummaryResponse = {
  providers: ProviderUsageSummary[];
};
