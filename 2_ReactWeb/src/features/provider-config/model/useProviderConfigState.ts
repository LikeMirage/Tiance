import { useEffect, useMemo, useState } from "react";

import { subscribeLlmUsageChanged } from "../../../entities/llm-usage/model/usageRefreshEvents";
import type { ProviderCatalogEntry } from "../../../entities/llm-provider/model/providerCatalog";
import type {
  ProviderAuthScheme,
  ProviderModelDiscoveryStrategy,
} from "../../../entities/llm-provider/model/providerCatalog";
import type { ProviderConfig } from "../../../entities/llm-provider/model/providerConfig";
import type { ProviderReasoningReplayMode } from "../../../entities/llm-provider/model/providerConfig";
import { emitLlmModelCatalogChanged } from "../../../entities/llm-provider/model/modelCatalogEvents";
import { getProviderConfigs } from "../../../services/llm/getProviderConfigs";
import { saveProviderConfig } from "../../../services/llm/saveProviderConfig";
import { saveProviderPromptCachePolicy } from "../../../services/llm/saveProviderPromptCachePolicy";
import {
  createApiKeyDraft,
  getNextApiKeyIndex,
  mergeProviderDraftAfterSave,
  formatPromptCacheRetention,
  parsePromptCacheRetentionSeconds,
  parsePollWeight,
  resolveEnabledAfterApiKeyEdit,
  resolveEnabledForApiKeys,
  syncProviderDrafts,
} from "./providerConfigDraftRules";
import { deriveProviderModelDiscoveryUrl } from "./deriveProviderModelDiscoveryUrl";
import type { ProviderConfigDraft } from "./providerConfigDraftTypes";

export interface UseProviderConfigStateResult {
  addSelectedApiKey: () => void;
  clearSelectedApiKey: (apiKeyId: string) => void;
  error: string | null;
  isLoading: boolean;
  isSelectedApiBaseUrlDirty: boolean;
  isSelectedModelDiscoveryUrlDirty: boolean;
  removeSelectedApiKeyIfEmpty: (apiKeyId: string) => void;
  resetSelectedApiBaseUrl: () => void;
  resetSelectedModelDiscoveryUrl: () => void;
  saveSelectedProviderConfig: () => Promise<boolean>;
  saveSelectedPromptCachePolicy: () => Promise<boolean>;
  selectedDraft: ProviderConfigDraft | null;
  savingProviderId: string | null;
  toggleSelectedEnabled: () => void;
  updateSelectedApiBaseUrl: (value: string) => void;
  updateSelectedAuthScheme: (value: ProviderAuthScheme) => void;
  updateSelectedModelDiscoveryUrl: (value: string) => void;
  updateSelectedModelDiscoveryStrategy: (
    value: ProviderModelDiscoveryStrategy,
  ) => void;
  updateSelectedModelDiscoveryAuthScheme: (value: ProviderAuthScheme) => void;
  updateSelectedPromptCacheRetentionUnit: (value: "hours" | "minutes") => void;
  updateSelectedPromptCacheRetentionValue: (value: string) => void;
  updateSelectedReasoningReplayMode: (value: ProviderReasoningReplayMode) => void;
  updateSelectedApiKey: (apiKeyId: string, value: string) => void;
  updateSelectedApiKeyPollWeight: (apiKeyId: string, value: string) => void;
}

export function useProviderConfigState(
  providers: ProviderCatalogEntry[],
  selectedProviderId: string | null,
): UseProviderConfigStateResult {
  const [drafts, setDrafts] = useState<Record<string, ProviderConfigDraft>>({});
  const [persistedConfigs, setPersistedConfigs] = useState<Record<string, ProviderConfig>>({});
  const [hasLoadedProviderConfigs, setHasLoadedProviderConfigs] = useState(false);
  const [savingProviderId, setSavingProviderId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isCancelled = false;

    const loadProviderConfigs = async () => {
      try {
        const response = await getProviderConfigs();
        if (isCancelled) {
          return;
        }

        setPersistedConfigs(
          Object.fromEntries(response.items.map((item) => [item.provider_id, item])),
        );
        setHasLoadedProviderConfigs(true);
        setError(null);
      } catch (loadError) {
        if (isCancelled) {
          return;
        }

        setError(
          loadError instanceof Error ? loadError.message : "供应商配置载入失败。",
        );
      }
    };

    void loadProviderConfigs();

    return () => {
      isCancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedProviderId) {
      return;
    }

    let isCancelled = false;
    const reloadSelectedProviderConfig = async () => {
      try {
        const response = await getProviderConfigs();
        if (isCancelled) {
          return;
        }

        setPersistedConfigs((current) => ({
          ...current,
          ...Object.fromEntries(response.items.map((item) => [item.provider_id, item])),
        }));
      } catch {
        return;
      }
    };
    const unsubscribeUsageChanged = subscribeLlmUsageChanged((detail) => {
      if (!detail.providerId || detail.providerId === selectedProviderId) {
        void reloadSelectedProviderConfig();
      }
    });

    return () => {
      isCancelled = true;
      unsubscribeUsageChanged();
    };
  }, [selectedProviderId]);

  useEffect(() => {
    if (!hasLoadedProviderConfigs) {
      return;
    }

    setDrafts((current) => syncProviderDrafts(current, providers, persistedConfigs));
  }, [hasLoadedProviderConfigs, persistedConfigs, providers]);

  const selectedDraft = useMemo(() => {
    if (!selectedProviderId) {
      return null;
    }

    return drafts[selectedProviderId] ?? null;
  }, [drafts, selectedProviderId]);

  const updateSelectedApiKey = (apiKeyId: string, value: string) => {
    if (!selectedProviderId) {
      return;
    }

    setDrafts((current) => {
      const draft = current[selectedProviderId];
      if (!draft) {
        return current;
      }

      const nextApiKeys = draft.apiKeys.map((apiKey) =>
        apiKey.id === apiKeyId && apiKey.value !== value
          ? {
              ...apiKey,
              apiKeyHint: value.trim().length > 0 ? null : apiKey.apiKeyHint,
              hasStoredApiKey: value.trim().length > 0 ? false : apiKey.hasStoredApiKey,
              value,
            }
          : apiKey,
      );

      if (nextApiKeys === draft.apiKeys) {
        return current;
      }

      return {
        ...current,
        [selectedProviderId]: {
          ...draft,
          apiKeys: nextApiKeys,
          enabled: resolveEnabledAfterApiKeyEdit(draft, nextApiKeys),
        },
      };
    });
  };

  const updateSelectedApiKeyPollWeight = (apiKeyId: string, value: string) => {
    if (!selectedProviderId) {
      return;
    }

    setDrafts((current) => {
      const draft = current[selectedProviderId];
      if (!draft) {
        return current;
      }

      const nextApiKeys = draft.apiKeys.map((apiKey) =>
        apiKey.id === apiKeyId && apiKey.pollWeight !== value
          ? {
              ...apiKey,
              pollWeight: value,
            }
          : apiKey,
      );

      if (nextApiKeys === draft.apiKeys) {
        return current;
      }

      return {
        ...current,
        [selectedProviderId]: {
          ...draft,
          apiKeys: nextApiKeys,
        },
      };
    });
  };

  const clearSelectedApiKey = (apiKeyId: string) => {
    if (!selectedProviderId || !selectedDraft) {
      return;
    }

    const nextApiKeys = selectedDraft.apiKeys.map((apiKey) =>
      apiKey.id === apiKeyId
        ? {
            ...apiKey,
            apiKeyHint: null,
            hasStoredApiKey: false,
            value: "",
          }
        : apiKey,
    );
    const nextDraft = {
      ...selectedDraft,
      apiKeys: nextApiKeys,
      enabled: resolveEnabledForApiKeys(selectedDraft, nextApiKeys),
    };

    setDrafts((current) => ({
      ...current,
      [selectedProviderId]: nextDraft,
    }));
  };

  const updateSelectedApiBaseUrl = (value: string) => {
    if (!selectedProviderId) {
      return;
    }

    setDrafts((current) => {
      const draft = current[selectedProviderId];
      if (!draft || draft.apiBaseUrl === value) {
        return current;
      }

      const modelDiscoveryUrl = draft.modelDiscoveryUrlAuto
        ? deriveProviderModelDiscoveryUrl(
            value,
            draft.protocolFamily,
            draft.presetApiBaseUrl,
            draft.presetModelDiscoveryUrl,
          )
        : draft.modelDiscoveryUrl;
      return {
        ...current,
        [selectedProviderId]: {
          ...draft,
          apiBaseUrl: value,
          modelDiscoveryUrl,
        },
      };
    });
  };

  const updateSelectedModelDiscoveryUrl = (value: string) => {
    if (!selectedProviderId) {
      return;
    }

    setDrafts((current) => {
      const draft = current[selectedProviderId];
      if (
        !draft
        || (draft.modelDiscoveryUrl === value && !draft.modelDiscoveryUrlAuto)
      ) {
        return current;
      }
      return {
        ...current,
        [selectedProviderId]: {
          ...draft,
          modelDiscoveryUrl: value,
          modelDiscoveryUrlAuto: false,
        },
      };
    });
  };

  const updateSelectedPromptCacheRetentionValue = (value: string) => {
    if (!selectedProviderId) {
      return;
    }
    setDrafts((current) => {
      const draft = current[selectedProviderId];
      if (!draft || draft.promptCacheRetentionValue === value) {
        return current;
      }
      return {
        ...current,
        [selectedProviderId]: {
          ...draft,
          promptCacheRetentionValue: value,
        },
      };
    });
  };

  const resetSelectedApiBaseUrl = () => {
    if (!selectedProviderId || !selectedDraft) {
      return;
    }

    if (selectedDraft.apiBaseUrl === selectedDraft.presetApiBaseUrl) {
      return;
    }

    const nextDraftToSave: ProviderConfigDraft = {
      ...selectedDraft,
      apiBaseUrl: selectedDraft.presetApiBaseUrl,
      modelDiscoveryUrl: selectedDraft.modelDiscoveryUrlAuto
        ? deriveProviderModelDiscoveryUrl(
            selectedDraft.presetApiBaseUrl,
            selectedDraft.protocolFamily,
            selectedDraft.presetApiBaseUrl,
            selectedDraft.presetModelDiscoveryUrl,
          )
        : selectedDraft.modelDiscoveryUrl,
    };
    setDrafts((current) => {
      if (!current[selectedProviderId]) {
        return current;
      }

      return {
        ...current,
        [selectedProviderId]: nextDraftToSave,
      };
    });
    void persistProviderDraft(selectedProviderId, nextDraftToSave);
  };

  const resetSelectedModelDiscoveryUrl = () => {
    if (!selectedProviderId || !selectedDraft) {
      return;
    }
    if (selectedDraft.modelDiscoveryUrlAuto) {
      return;
    }

    const nextDraftToSave: ProviderConfigDraft = {
      ...selectedDraft,
      modelDiscoveryUrl: deriveProviderModelDiscoveryUrl(
        selectedDraft.apiBaseUrl,
        selectedDraft.protocolFamily,
        selectedDraft.presetApiBaseUrl,
        selectedDraft.presetModelDiscoveryUrl,
      ),
      modelDiscoveryUrlAuto: true,
    };
    setDrafts((current) => ({
      ...current,
      [selectedProviderId]: nextDraftToSave,
    }));
    void persistProviderDraft(selectedProviderId, nextDraftToSave);
  };

  const toggleSelectedEnabled = () => {
    if (!selectedProviderId || !selectedDraft) {
      return;
    }

    if (!selectedDraft.enabled && selectedDraft.apiBaseUrl.trim().length === 0) {
      setError("当前协议未配置完整生成 API 地址，不能启用供应商。");
      return;
    }

    const nextDraftToSave: ProviderConfigDraft = {
      ...selectedDraft,
      enabled: !selectedDraft.enabled,
      hasManualEnabledOverride: true,
    };
    setDrafts((current) => {
      if (!current[selectedProviderId]) {
        return current;
      }

      return {
        ...current,
        [selectedProviderId]: nextDraftToSave,
      };
    });
    void persistProviderDraft(selectedProviderId, nextDraftToSave);
  };

  const addSelectedApiKey = () => {
    if (!selectedProviderId) {
      return;
    }

    setDrafts((current) => {
      const draft = current[selectedProviderId];
      if (!draft) {
        return current;
      }

      const nextKeyIndex = getNextApiKeyIndex(
        selectedProviderId,
        draft.apiKeys,
      );
      return {
        ...current,
        [selectedProviderId]: {
          ...draft,
          apiKeys: [
            ...draft.apiKeys,
            createApiKeyDraft(selectedProviderId, nextKeyIndex),
          ],
        },
      };
    });
  };

  const removeSelectedApiKeyIfEmpty = (apiKeyId: string) => {
    if (!selectedProviderId || !selectedDraft) {
      return;
    }

    const targetKey = selectedDraft.apiKeys.find((apiKey) => apiKey.id === apiKeyId);
    if (!targetKey) {
      return;
    }

    let nextDraft = selectedDraft;
    if (
      selectedDraft.apiKeys.length > 1 &&
      !targetKey.hasStoredApiKey &&
      targetKey.value.trim().length === 0
    ) {
      const nextApiKeys = selectedDraft.apiKeys.filter(
        (apiKey) => apiKey.id !== apiKeyId,
      );
      nextDraft = {
        ...selectedDraft,
        apiKeys: nextApiKeys,
        enabled: resolveEnabledForApiKeys(selectedDraft, nextApiKeys),
      };
    }

    setDrafts((current) => ({
      ...current,
      [selectedProviderId]: nextDraft,
    }));
    void persistProviderDraft(selectedProviderId, nextDraft);
  };

  const persistProviderDraft = async (
    providerId: string,
    draft: ProviderConfigDraft,
  ) => {
    if (!hasLoadedProviderConfigs) {
      setError("供应商配置仍在载入，暂不能保存。");
      return false;
    }

    const provider = providers.find((item) => item.provider_id === providerId);
    if (!provider) {
      return false;
    }

    setSavingProviderId(providerId);
    try {
      const apiKeysToSave = draft.apiKeys
        .filter((apiKey) => apiKey.value.trim().length > 0 || apiKey.hasStoredApiKey)
        .map((apiKey) => ({
          api_key:
            apiKey.value.trim().length > 0 ? apiKey.value.trim() : undefined,
          key_id: apiKey.id,
          poll_weight: parsePollWeight(apiKey.pollWeight),
        }));
      const savedConfig = await saveProviderConfig(providerId, {
        api_base_url: draft.apiBaseUrl,
        protocol_family: draft.protocolFamily,
        auth_scheme: draft.authScheme,
        model_discovery_url: draft.modelDiscoveryUrl.trim() || null,
        model_discovery_strategy: draft.modelDiscoveryStrategy,
        model_discovery_auth_scheme: draft.modelDiscoveryAuthScheme,
        enabled: draft.enabled,
        api_keys: apiKeysToSave,
        reasoning_replay_mode: draft.reasoningReplayMode,
      });

      setPersistedConfigs((current) => ({
        ...current,
        [providerId]: savedConfig,
      }));
      setDrafts((current) => ({
        ...current,
        [providerId]: mergeProviderDraftAfterSave(provider, savedConfig),
      }));
      emitLlmModelCatalogChanged({ providerId });
      setError(null);
      return true;
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "供应商配置保存失败。");
      return false;
    } finally {
      setSavingProviderId((current) => (current === providerId ? null : current));
    }
  };

  const saveSelectedProviderConfig = async () => {
    if (!selectedProviderId || !selectedDraft) {
      return false;
    }

    return persistProviderDraft(selectedProviderId, selectedDraft);
  };

  const persistPromptCachePolicy = async (
    providerId: string,
    draft: ProviderConfigDraft,
  ) => {
    const seconds = parsePromptCacheRetentionSeconds(
      draft.promptCacheRetentionValue,
      draft.promptCacheRetentionUnit,
    );
    if (seconds === null) {
      setError("缓存有效期必须是大于 0 的整数。");
      return false;
    }

    setSavingProviderId(providerId);
    try {
      const saved = await saveProviderPromptCachePolicy(providerId, seconds);
      const formatted = formatPromptCacheRetention(
        saved.prompt_cache_retention_seconds,
      );
      setPersistedConfigs((current) => {
        const config = current[providerId];
        if (!config) {
          return current;
        }
        return {
          ...current,
          [providerId]: {
            ...config,
            prompt_cache_retention_seconds:
              saved.prompt_cache_retention_seconds,
          },
        };
      });
      setDrafts((current) => {
        const currentDraft = current[providerId];
        if (!currentDraft) {
          return current;
        }
        return {
          ...current,
          [providerId]: {
            ...currentDraft,
            promptCacheRetentionUnit: formatted.unit,
            promptCacheRetentionValue: formatted.value,
            persistedPromptCacheRetentionSeconds:
              saved.prompt_cache_retention_seconds,
          },
        };
      });
      setError(null);
      return true;
    } catch (saveError) {
      setError(
        saveError instanceof Error ? saveError.message : "缓存设置保存失败。",
      );
      return false;
    } finally {
      setSavingProviderId((current) => (current === providerId ? null : current));
    }
  };

  const saveSelectedPromptCachePolicy = async () => {
    if (!selectedProviderId || !selectedDraft) {
      return false;
    }
    return persistPromptCachePolicy(selectedProviderId, selectedDraft);
  };

  const updateSelectedPromptCacheRetentionUnit = (
    value: "hours" | "minutes",
  ) => {
    if (!selectedProviderId || !selectedDraft) {
      return;
    }
    const nextDraft = {
      ...selectedDraft,
      promptCacheRetentionUnit: value,
    };
    setDrafts((current) => ({
      ...current,
      [selectedProviderId]: nextDraft,
    }));
    void persistPromptCachePolicy(selectedProviderId, nextDraft);
  };

  const persistSelectedDraftUpdate = (
    patch: Partial<ProviderConfigDraft>,
  ) => {
    if (!selectedProviderId || !selectedDraft) {
      return;
    }
    const nextDraft = { ...selectedDraft, ...patch };
    setDrafts((current) => ({
      ...current,
      [selectedProviderId]: nextDraft,
    }));
    void persistProviderDraft(selectedProviderId, nextDraft);
  };

  const updateSelectedAuthScheme = (value: ProviderAuthScheme) => {
    persistSelectedDraftUpdate({ authScheme: value });
  };

  const updateSelectedModelDiscoveryStrategy = (
    value: ProviderModelDiscoveryStrategy,
  ) => {
    persistSelectedDraftUpdate({ modelDiscoveryStrategy: value });
  };

  const updateSelectedModelDiscoveryAuthScheme = (value: ProviderAuthScheme) => {
    persistSelectedDraftUpdate({ modelDiscoveryAuthScheme: value });
  };

  const updateSelectedReasoningReplayMode = (value: ProviderReasoningReplayMode) => {
    persistSelectedDraftUpdate({ reasoningReplayMode: value });
  };

  return {
    addSelectedApiKey,
    clearSelectedApiKey,
    error,
    isLoading: !hasLoadedProviderConfigs,
    isSelectedApiBaseUrlDirty:
      selectedDraft !== null && selectedDraft.apiBaseUrl !== selectedDraft.presetApiBaseUrl,
    isSelectedModelDiscoveryUrlDirty:
      selectedDraft !== null && !selectedDraft.modelDiscoveryUrlAuto,
    removeSelectedApiKeyIfEmpty,
    resetSelectedApiBaseUrl,
    resetSelectedModelDiscoveryUrl,
    saveSelectedProviderConfig,
    saveSelectedPromptCachePolicy,
    selectedDraft,
    savingProviderId,
    toggleSelectedEnabled,
    updateSelectedApiBaseUrl,
    updateSelectedAuthScheme,
    updateSelectedModelDiscoveryUrl,
    updateSelectedModelDiscoveryStrategy,
    updateSelectedModelDiscoveryAuthScheme,
    updateSelectedPromptCacheRetentionUnit,
    updateSelectedPromptCacheRetentionValue,
    updateSelectedReasoningReplayMode,
    updateSelectedApiKey,
    updateSelectedApiKeyPollWeight,
  };
}
