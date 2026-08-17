import type {
  ProviderAuthScheme,
  ProviderModelDiscoveryStrategy,
  ProviderProtocolFamily,
} from "../../../entities/llm-provider/model/providerCatalog";
import type { ProviderReasoningReplayMode } from "../../../entities/llm-provider/model/providerConfig";

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
  modelDiscoveryUrlAuto: boolean;
  modelDiscoveryStrategy: ProviderModelDiscoveryStrategy;
  modelDiscoveryAuthScheme: ProviderAuthScheme;
  apiKeys: ProviderApiKeyDraft[];
  enabled: boolean;
  promptCacheRetentionUnit: "hours" | "minutes";
  promptCacheRetentionValue: string;
  reasoningReplayMode: ProviderReasoningReplayMode;
  hasManualEnabledOverride: boolean;
  persistedUpdatedAt: string | null;
  persistedPromptCacheRetentionSeconds: number;
  presetApiBaseUrl: string;
  presetModelDiscoveryUrl: string;
};
