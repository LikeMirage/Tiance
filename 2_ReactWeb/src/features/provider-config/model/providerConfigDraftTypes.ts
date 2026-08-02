import type {
  ProviderAuthScheme,
  ProviderModelDiscoveryStrategy,
  ProviderProtocolFamily,
} from "../../../entities/llm-provider/model/providerCatalog";

export type ProviderApiKeyDraft = {
  apiKeyHint: string | null;
  hasStoredApiKey: boolean;
  id: string;
  pollWeight: string;
  rpm: number;
  value: string;
};

export type ProviderConfigDraft = {
  apiBaseUrl: string;
  protocolFamily: ProviderProtocolFamily;
  authScheme: ProviderAuthScheme;
  modelDiscoveryUrl: string;
  modelDiscoveryStrategy: ProviderModelDiscoveryStrategy;
  modelDiscoveryAuthScheme: ProviderAuthScheme;
  apiKeys: ProviderApiKeyDraft[];
  enabled: boolean;
  promptCacheRetentionUnit: "hours" | "minutes";
  promptCacheRetentionValue: string;
  hasManualEnabledOverride: boolean;
  persistedUpdatedAt: string | null;
  persistedPromptCacheRetentionSeconds: number;
  presetApiBaseUrl: string;
  presetModelDiscoveryUrl: string;
};
