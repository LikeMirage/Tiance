export interface ProviderCatalogEntry {
  provider_id: string;
  display_name: string;
  protocol_family: ProviderProtocolFamily;
  auth_scheme: ProviderAuthScheme;
  generation_auth_schemes: Partial<Record<ProviderProtocolFamily, ProviderAuthScheme>>;
  api_base_url: string;
  generation_urls: Partial<Record<ProviderProtocolFamily, string>>;
  text_generation_url_template: string;
  model_discovery_strategy: ProviderModelDiscoveryStrategy;
  model_discovery_auth_scheme: ProviderAuthScheme;
  model_discovery_url: string | null;
  preset_generation_urls: Partial<Record<ProviderProtocolFamily, string>>;
  preset_generation_auth_schemes: Partial<Record<ProviderProtocolFamily, ProviderAuthScheme>>;
  preset_model_discovery_strategy: ProviderModelDiscoveryStrategy | null;
  preset_model_discovery_auth_scheme: ProviderAuthScheme | null;
  preset_model_discovery_url: string | null;
  created_at: string | null;
}

export interface ProviderCatalogResponse {
  count: number;
  items: ProviderCatalogEntry[];
  errors: ProviderCatalogLoadError[];
}

export interface ProviderCatalogLoadError {
  provider_id: string;
  code: "invalid_provider_package";
  message: string;
}

export interface ProviderCatalogOrderResponse {
  count: number;
  provider_ids: string[];
}

export type ProviderProtocolFamily =
  | "openai_compatible"
  | "openai_responses"
  | "anthropic_messages"
  | "gemini_generate_content";

export type ProviderAuthScheme =
  | "bearer_token"
  | "x_api_key"
  | "x_goog_api_key"
  | "api_key_query";

export type ProviderModelDiscoveryStrategy =
  | "openai_models"
  | "anthropic_models"
  | "gemini_models";

export interface ProviderCatalogCreateRequest {
  display_name: string;
  category_id?: string | null;
}

export interface ProviderCatalogUpdateRequest {
  display_name?: string;
  protocol_family?: ProviderProtocolFamily;
}

export interface ProviderCatalogOrderSaveRequest {
  provider_ids: string[];
}
