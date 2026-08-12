import type { ProviderCatalogEntry } from "../../../entities/llm-provider/model/providerCatalog";
import type { ProviderConfig } from "../../../entities/llm-provider/model/providerConfig";
import {
  deriveProviderModelDiscoveryUrl,
  isProviderModelDiscoveryUrlAuto,
} from "./deriveProviderModelDiscoveryUrl";
import type { ProviderApiKeyDraft, ProviderConfigDraft } from "./providerConfigDraftTypes";

export function syncProviderDrafts(
  current: Record<string, ProviderConfigDraft>,
  providers: ProviderCatalogEntry[],
  persistedConfigs: Record<string, ProviderConfig>,
) {
  const next: Record<string, ProviderConfigDraft> = {};

  for (const provider of providers) {
    const existingDraft = current[provider.provider_id];
    const persistedConfig = persistedConfigs[provider.provider_id];

    if (!existingDraft) {
      next[provider.provider_id] = createProviderDraft(provider, persistedConfig);
      continue;
    }

    if (existingDraft.protocolFamily !== provider.protocol_family) {
      next[provider.provider_id] = createProviderDraft(provider, persistedConfig);
      continue;
    }

    if (
      persistedConfig &&
      (
        existingDraft.persistedUpdatedAt !== persistedConfig.updated_at ||
        hasApiKeyRpmChanged(existingDraft, persistedConfig)
      ) &&
      !hasPendingApiKeyValue(existingDraft)
    ) {
      next[provider.provider_id] = createProviderDraft(provider, persistedConfig);
      continue;
    }

    if (
      persistedConfig
      && existingDraft.persistedPromptCacheRetentionSeconds
        !== persistedConfig.prompt_cache_retention_seconds
    ) {
      next[provider.provider_id] = createProviderDraft(provider, persistedConfig);
      continue;
    }

    const wasUsingPreset = existingDraft.apiBaseUrl === existingDraft.presetApiBaseUrl;
    const activeApiBaseUrl =
      persistedConfig?.generation_urls[provider.protocol_family]
      ?? (persistedConfig?.protocol_family === provider.protocol_family
        ? persistedConfig.api_base_url
        : undefined)
      ?? provider.generation_urls[provider.protocol_family]
      ?? provider.api_base_url;
    const presetApiBaseUrl = resolvePresetApiBaseUrl(
      provider,
      provider.protocol_family,
    );
    const nextApiKeys = normalizeApiKeys(provider.provider_id, existingDraft);
    const hasManualEnabledOverride = existingDraft.hasManualEnabledOverride === true;
    const presetModelDiscoveryUrl = resolvePresetModelDiscoveryUrl(provider);
    const nextApiBaseUrl = wasUsingPreset ? activeApiBaseUrl : existingDraft.apiBaseUrl;
    const wasUsingAutomaticModelUrl = existingDraft.modelDiscoveryUrlAuto ??
      isProviderModelDiscoveryUrlAuto(
        existingDraft.modelDiscoveryUrl,
        existingDraft.apiBaseUrl,
        existingDraft.protocolFamily,
        existingDraft.presetApiBaseUrl,
        existingDraft.presetModelDiscoveryUrl,
      );
    next[provider.provider_id] = {
      apiBaseUrl: nextApiBaseUrl,
      protocolFamily: provider.protocol_family,
      authScheme: existingDraft.authScheme,
      modelDiscoveryUrl: wasUsingAutomaticModelUrl
        ? deriveProviderModelDiscoveryUrl(
            nextApiBaseUrl,
            provider.protocol_family,
            presetApiBaseUrl,
            presetModelDiscoveryUrl,
          )
        : existingDraft.modelDiscoveryUrl,
      modelDiscoveryUrlAuto: wasUsingAutomaticModelUrl,
      modelDiscoveryStrategy: existingDraft.modelDiscoveryStrategy,
      modelDiscoveryAuthScheme: existingDraft.modelDiscoveryAuthScheme,
      apiKeys: nextApiKeys,
      enabled: hasManualEnabledOverride ? existingDraft.enabled : hasAnyApiKey(nextApiKeys),
      promptCacheRetentionUnit: existingDraft.promptCacheRetentionUnit,
      promptCacheRetentionValue: existingDraft.promptCacheRetentionValue,
      hasManualEnabledOverride,
      persistedUpdatedAt: existingDraft.persistedUpdatedAt ?? null,
      persistedPromptCacheRetentionSeconds:
        existingDraft.persistedPromptCacheRetentionSeconds,
      presetApiBaseUrl,
      presetModelDiscoveryUrl,
    };
  }

  return next;
}

export function createApiKeyDraft(providerId: string, index: number): ProviderApiKeyDraft {
  return {
    apiKeyHint: null,
    hasStoredApiKey: false,
    id: `${providerId}-key-${index}`,
    pollWeight: "1",
    rpm: 0,
    value: "",
  };
}

export function mergeProviderDraftAfterSave(
  provider: ProviderCatalogEntry,
  savedConfig: ProviderConfig,
): ProviderConfigDraft {
  const cacheRetention = formatPromptCacheRetention(
    savedConfig.prompt_cache_retention_seconds,
  );
  const activeApiBaseUrl =
    savedConfig.generation_urls[savedConfig.protocol_family] ?? savedConfig.api_base_url;
  const presetApiBaseUrl = resolvePresetApiBaseUrl(
    provider,
    savedConfig.protocol_family,
  );
  const presetModelDiscoveryUrl = resolvePresetModelDiscoveryUrl(provider);
  const savedModelDiscoveryUrl = savedConfig.model_discovery_url ?? "";
  const modelDiscoveryUrlAuto = isProviderModelDiscoveryUrlAuto(
    savedModelDiscoveryUrl,
    activeApiBaseUrl,
    savedConfig.protocol_family,
    presetApiBaseUrl,
    presetModelDiscoveryUrl,
  );
  const modelDiscoveryUrl = modelDiscoveryUrlAuto
    ? deriveProviderModelDiscoveryUrl(
        activeApiBaseUrl,
        savedConfig.protocol_family,
        presetApiBaseUrl,
        presetModelDiscoveryUrl,
      )
    : savedModelDiscoveryUrl;
  const savedApiKeys =
    savedConfig.api_keys.length > 0
      ? savedConfig.api_keys.map((apiKey) => ({
          apiKeyHint: apiKey.has_api_key ? apiKey.api_key_hint : null,
          hasStoredApiKey: apiKey.has_api_key,
          id: apiKey.key_id,
          pollWeight: String(apiKey.poll_weight),
          rpm: apiKey.rpm,
          value: "",
        }))
      : [createApiKeyDraft(provider.provider_id, 1)];

  return {
    apiBaseUrl: activeApiBaseUrl,
    protocolFamily: savedConfig.protocol_family,
    authScheme: savedConfig.auth_scheme,
    modelDiscoveryUrl,
    modelDiscoveryUrlAuto,
    modelDiscoveryStrategy: savedConfig.model_discovery_strategy,
    modelDiscoveryAuthScheme: savedConfig.model_discovery_auth_scheme,
    apiKeys: savedApiKeys,
    enabled: savedConfig.enabled,
    promptCacheRetentionUnit: cacheRetention.unit,
    promptCacheRetentionValue: cacheRetention.value,
    hasManualEnabledOverride: true,
    persistedUpdatedAt: savedConfig.updated_at,
    persistedPromptCacheRetentionSeconds: savedConfig.prompt_cache_retention_seconds,
    presetApiBaseUrl,
    presetModelDiscoveryUrl,
  };
}

export function getNextApiKeyIndex(
  providerId: string,
  apiKeys: ProviderApiKeyDraft[],
) {
  const idPrefix = `${providerId}-key-`;
  const maxExistingIndex = apiKeys.reduce((maxIndex, apiKey) => {
    if (!apiKey.id.startsWith(idPrefix)) {
      return maxIndex;
    }

    const parsedIndex = Number.parseInt(apiKey.id.slice(idPrefix.length), 10);
    if (Number.isNaN(parsedIndex)) {
      return maxIndex;
    }

    return Math.max(maxIndex, parsedIndex);
  }, 0);

  return maxExistingIndex + 1;
}

export function resolveEnabledForApiKeys(
  draft: ProviderConfigDraft,
  apiKeys: ProviderApiKeyDraft[],
) {
  if (draft.hasManualEnabledOverride) {
    return draft.enabled;
  }

  return hasAnyApiKey(apiKeys);
}

export function resolveEnabledAfterApiKeyEdit(
  draft: ProviderConfigDraft,
  apiKeys: ProviderApiKeyDraft[],
) {
  if (hasPendingApiKeyValueInList(apiKeys)) {
    return true;
  }

  return resolveEnabledForApiKeys(draft, apiKeys);
}

export function parsePollWeight(value: string) {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed) || parsed < 0) {
    return 1;
  }
  return parsed;
}

function createProviderDraft(
  provider: ProviderCatalogEntry,
  persistedConfig?: ProviderConfig,
): ProviderConfigDraft {
  const activeApiBaseUrl =
    persistedConfig?.generation_urls[provider.protocol_family]
    ?? (persistedConfig?.protocol_family === provider.protocol_family
      ? persistedConfig.api_base_url
      : undefined)
    ?? provider.generation_urls[provider.protocol_family]
    ?? provider.api_base_url;
  const presetApiBaseUrl = resolvePresetApiBaseUrl(
    provider,
    provider.protocol_family,
  );
  const activeModelDiscoveryUrl =
    persistedConfig?.model_discovery_url ?? provider.model_discovery_url ?? "";
  const presetModelDiscoveryUrl = resolvePresetModelDiscoveryUrl(provider);
  const modelDiscoveryUrlAuto = resolveModelDiscoveryUrlAuto(
    provider,
    persistedConfig,
    activeModelDiscoveryUrl,
    activeApiBaseUrl,
    presetApiBaseUrl,
    presetModelDiscoveryUrl,
  );
  const modelDiscoveryUrl = modelDiscoveryUrlAuto
    ? deriveProviderModelDiscoveryUrl(
        activeApiBaseUrl,
        provider.protocol_family,
        presetApiBaseUrl,
        presetModelDiscoveryUrl,
      )
    : activeModelDiscoveryUrl;
  const cacheRetention = formatPromptCacheRetention(
    persistedConfig?.prompt_cache_retention_seconds ?? 5 * 60,
  );
  if (persistedConfig) {
    return {
      apiBaseUrl: activeApiBaseUrl,
      protocolFamily: provider.protocol_family,
      authScheme:
        persistedConfig.generation_auth_schemes[provider.protocol_family]
        ?? provider.generation_auth_schemes[provider.protocol_family]
        ?? persistedConfig.auth_scheme
        ?? provider.auth_scheme,
      modelDiscoveryUrl,
      modelDiscoveryUrlAuto,
      modelDiscoveryStrategy: persistedConfig.model_discovery_strategy,
      modelDiscoveryAuthScheme: persistedConfig.model_discovery_auth_scheme,
      apiKeys:
        persistedConfig.api_keys.length > 0
          ? persistedConfig.api_keys.map((apiKey) => ({
              apiKeyHint: apiKey.has_api_key ? apiKey.api_key_hint : null,
              hasStoredApiKey: apiKey.has_api_key,
              id: apiKey.key_id,
              pollWeight: String(apiKey.poll_weight),
              rpm: apiKey.rpm,
              value: "",
            }))
          : [createApiKeyDraft(provider.provider_id, 1)],
      enabled: activeApiBaseUrl.trim().length > 0 && persistedConfig.enabled,
      promptCacheRetentionUnit: cacheRetention.unit,
      promptCacheRetentionValue: cacheRetention.value,
      hasManualEnabledOverride: true,
      persistedUpdatedAt: persistedConfig.updated_at,
      persistedPromptCacheRetentionSeconds: persistedConfig.prompt_cache_retention_seconds,
      presetApiBaseUrl,
      presetModelDiscoveryUrl,
    };
  }

  return {
    apiBaseUrl: activeApiBaseUrl,
    protocolFamily: provider.protocol_family,
    authScheme:
      provider.generation_auth_schemes[provider.protocol_family]
      ?? provider.auth_scheme,
    modelDiscoveryUrl,
    modelDiscoveryUrlAuto,
    modelDiscoveryStrategy: provider.model_discovery_strategy,
    modelDiscoveryAuthScheme: provider.model_discovery_auth_scheme,
    apiKeys: [createApiKeyDraft(provider.provider_id, 1)],
    enabled: false,
    promptCacheRetentionUnit: cacheRetention.unit,
    promptCacheRetentionValue: cacheRetention.value,
    hasManualEnabledOverride: false,
    persistedUpdatedAt: null,
    persistedPromptCacheRetentionSeconds: 5 * 60,
    presetApiBaseUrl,
    presetModelDiscoveryUrl,
  };
}

export function parsePromptCacheRetentionSeconds(
  value: string,
  unit: ProviderConfigDraft["promptCacheRetentionUnit"],
) {
  const amount = Number.parseInt(value, 10);
  if (!Number.isFinite(amount) || amount < 1) {
    return null;
  }
  return amount * (unit === "hours" ? 60 * 60 : 60);
}

export function formatPromptCacheRetention(seconds: number): {
  unit: ProviderConfigDraft["promptCacheRetentionUnit"];
  value: string;
} {
  const normalized = Math.max(60, Math.round(seconds));
  if (normalized % (60 * 60) === 0) {
    return { unit: "hours", value: String(normalized / (60 * 60)) };
  }
  return { unit: "minutes", value: String(Math.ceil(normalized / 60)) };
}

function resolvePresetApiBaseUrl(
  provider: ProviderCatalogEntry,
  protocolFamily: ProviderConfig["protocol_family"],
) {
  return provider.preset_generation_urls[protocolFamily] ?? "";
}

function resolvePresetModelDiscoveryUrl(provider: ProviderCatalogEntry) {
  return provider.preset_model_discovery_url ?? "";
}

function resolveModelDiscoveryUrlAuto(
  provider: ProviderCatalogEntry,
  persistedConfig: ProviderConfig | undefined,
  modelDiscoveryUrl: string,
  activeApiBaseUrl: string,
  presetApiBaseUrl: string,
  presetModelDiscoveryUrl: string,
) {
  if (
    isProviderModelDiscoveryUrlAuto(
      modelDiscoveryUrl,
      activeApiBaseUrl,
      provider.protocol_family,
      presetApiBaseUrl,
      presetModelDiscoveryUrl,
    )
  ) {
    return true;
  }

  const generationUrls = {
    ...provider.generation_urls,
    ...(persistedConfig?.generation_urls ?? {}),
  };
  return Object.entries(generationUrls).some(([protocolFamily, generationUrl]) =>
    isProviderModelDiscoveryUrlAuto(
      modelDiscoveryUrl,
      generationUrl,
      protocolFamily as ProviderConfig["protocol_family"],
      provider.preset_generation_urls[
        protocolFamily as ProviderConfig["protocol_family"]
      ] ?? "",
      presetModelDiscoveryUrl,
    ),
  );
}

function normalizeApiKeys(providerId: string, draft: Record<string, unknown>) {
  const rawApiKeys = Array.isArray(draft.apiKeys) ? draft.apiKeys : null;

  if (!rawApiKeys || rawApiKeys.length === 0) {
    return [createApiKeyDraft(providerId, 1)];
  }

  return rawApiKeys.map((rawApiKey, index) => {
    const entry = rawApiKey as Record<string, unknown>;
    return {
      apiKeyHint: typeof entry.apiKeyHint === "string" ? entry.apiKeyHint : null,
      hasStoredApiKey: entry.hasStoredApiKey === true,
      id:
        typeof entry.id === "string" && entry.id.length > 0
          ? entry.id
          : `${providerId}-key-${index + 1}`,
      pollWeight:
        typeof entry.pollWeight === "string" && entry.pollWeight.length > 0
          ? entry.pollWeight
          : "1",
      rpm: typeof entry.rpm === "number" ? entry.rpm : 0,
      value: typeof entry.value === "string" ? entry.value : "",
    };
  });
}

function hasAnyApiKey(apiKeys: ProviderApiKeyDraft[]) {
  return apiKeys.some(
    (apiKey) => apiKey.value.trim().length > 0 || apiKey.hasStoredApiKey,
  );
}

function hasPendingApiKeyValue(draft: ProviderConfigDraft) {
  return hasPendingApiKeyValueInList(draft.apiKeys);
}

function hasPendingApiKeyValueInList(apiKeys: ProviderApiKeyDraft[]) {
  return apiKeys.some((apiKey) => apiKey.value.trim().length > 0);
}

function hasApiKeyRpmChanged(draft: ProviderConfigDraft, config: ProviderConfig) {
  const rpmByKeyId = new Map(config.api_keys.map((apiKey) => [apiKey.key_id, apiKey.rpm]));
  return draft.apiKeys.some((apiKey) => apiKey.rpm !== (rpmByKeyId.get(apiKey.id) ?? 0));
}
