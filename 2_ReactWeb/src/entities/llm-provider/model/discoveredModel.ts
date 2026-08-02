export type DiscoveredModelCapability =
  | "reasoning"
  | "vision"
  | "websearch"
  | "embedding"
  | "rerank"
  | "function_calling";

export interface DiscoveredModelEntry {
  model_id: string;
  display_name: string;
  provider_id: string;
  family_group: string;
  capability_tags: DiscoveredModelCapability[];
}

export interface DiscoveredModelListResponse {
  count: number;
  items: DiscoveredModelEntry[];
}

export interface ProviderCloudModelCacheResponse extends DiscoveredModelListResponse {
  api_base_url: string;
  discovered_at: string | null;
  has_cache: boolean;
  protocol_family: string;
  provider_id: string;
}
