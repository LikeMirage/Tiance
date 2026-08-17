import type {
  ProviderAuthScheme,
  ProviderModelDiscoveryStrategy,
  ProviderProtocolFamily,
} from "./providerCatalog";

export type ProviderReasoningReplayMode = "never" | "tool_call_rounds" | "always";

export interface ProviderApiKeyConfig {
  key_id: string;
  has_api_key: boolean;
  api_key_hint: string | null;
  poll_weight: number;
  rpm: number;
}

export interface ProviderConfig {
  provider_id: string;
  api_base_url: string;
  protocol_family: ProviderProtocolFamily;
  generation_urls: Partial<Record<ProviderProtocolFamily, string>>;
  auth_scheme: ProviderAuthScheme;
  generation_auth_schemes: Partial<Record<ProviderProtocolFamily, ProviderAuthScheme>>;
  model_discovery_url: string | null;
  model_discovery_strategy: ProviderModelDiscoveryStrategy;
  model_discovery_auth_scheme: ProviderAuthScheme;
  enabled: boolean;
  prompt_cache_retention_seconds: number;
  reasoning_replay_mode: ProviderReasoningReplayMode;
  api_keys: ProviderApiKeyConfig[];
  created_at: string;
  updated_at: string;
}

export interface ProviderConfigListResponse {
  count: number;
  items: ProviderConfig[];
}

export interface ProviderModelCheckResult {
  provider_id: string;
  model_id: string;
  ok: boolean;
  checked_url: string;
  selected_key_id?: string | null;
  selected_api_key_hint?: string | null;
}

export interface ProviderApiKeyConfigSaveInput {
  key_id?: string;
  api_key?: string;
  poll_weight: number;
}

export interface ProviderConfigSaveRequest {
  api_base_url: string;
  protocol_family: ProviderProtocolFamily;
  auth_scheme: ProviderAuthScheme;
  model_discovery_url: string | null;
  model_discovery_strategy: ProviderModelDiscoveryStrategy;
  model_discovery_auth_scheme: ProviderAuthScheme;
  enabled: boolean;
  api_keys: ProviderApiKeyConfigSaveInput[];
  reasoning_replay_mode: ProviderReasoningReplayMode;
}

export interface ProviderPromptCachePolicyResponse {
  provider_id: string;
  prompt_cache_retention_seconds: number;
}
