import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type {
  DsLlmGenerationParams,
  DsLlmOutputFormat,
} from "../../../entities/llm-runtime/model/generationParams";
import type { DsLlmRuntimeCapabilities } from "../../../entities/llm-runtime/model/runtimeCapabilities";
import { subscribeLlmModelCatalogChanged } from "../../../entities/llm-provider/model/modelCatalogEvents";
import { getModelCatalog } from "../../../services/llm/getModelCatalog";
import { getRuntimeCapabilities } from "../../../services/llm/getRuntimeCapabilities";
import {
  getFunctionalModelProfileSettings,
} from "../../../services/llm/functionalModelSettings";
import {
  DEFAULT_FUNCTIONAL_MODEL_SETTINGS,
  FUNCTIONAL_MODEL_SETTINGS_VERSION,
  type FunctionalModelOption,
  type FunctionalModelProfileKey,
  type FunctionalModelProfileSettingsMap,
  type FunctionalModelSettings,
} from "./functionalModelSettings";
import {
  clearUnavailableProfileModel,
  getFunctionalModelKey,
  getModelCatalogKind,
  getStringSetting,
  normalizeProfileSettings,
  toFunctionalModelOption,
} from "./functionalModelSettingsRuntime";
import {
  isRuntimeCapabilitiesUnavailable,
  UNAVAILABLE_RUNTIME_CAPABILITIES,
} from "./unavailableRuntimeCapabilities";
import { useQueuedFunctionalModelSettingsSave } from "./useQueuedFunctionalModelSettingsSave";

export type { FunctionalModelOption } from "./functionalModelSettings";
export { getFunctionalModelKey } from "./functionalModelSettingsRuntime";

export type UseFunctionalModelSettingsResult<K extends FunctionalModelProfileKey> = {
  eligibleTextModels: FunctionalModelOption[];
  error: string | null;
  isLoadingModels: boolean;
  isLoadingSettings: boolean;
  reloadModels: (options?: ReloadFunctionalModelsOptions) => Promise<void>;
  resetPrompt: (options?: ResetFunctionalModelPromptOptions) => Promise<void>;
  resetSettings: () => Promise<void>;
  runtimeCapabilities: DsLlmRuntimeCapabilities;
  selectedModel: FunctionalModelOption | null;
  settings: FunctionalModelProfileSettingsMap[K];
  updateGenerationParam: <P extends keyof DsLlmGenerationParams>(
    key: P,
    value: DsLlmGenerationParams[P],
  ) => void;
  updateProfileSetting: <P extends keyof FunctionalModelProfileSettingsMap[K]>(
    key: P,
    value: FunctionalModelProfileSettingsMap[K][P],
  ) => void;
  updateOutputFormat: (format: DsLlmOutputFormat) => void;
};

type ReloadFunctionalModelsOptions = {
  clearUnavailableSelection?: boolean;
  silent?: boolean;
};

type ResetFunctionalModelPromptOptions = {
  key?: string;
  syncPromptKey?: string;
};

export function useFunctionalModelSettings<K extends FunctionalModelProfileKey>(
  profileKey: K,
): UseFunctionalModelSettingsResult<K> {
  const [eligibleTextModels, setEligibleTextModels] = useState<FunctionalModelOption[]>([]);
  const [isLoadingModels, setIsLoadingModels] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runtimeCapabilitiesError, setRuntimeCapabilitiesError] = useState<string | null>(null);
  const [allSettings, setAllSettings] = useState<FunctionalModelSettings>(() =>
    DEFAULT_FUNCTIONAL_MODEL_SETTINGS,
  );
  const [settingsVersion, setSettingsVersion] = useState(FUNCTIONAL_MODEL_SETTINGS_VERSION);
  const [hasLoadedPersistentSettings, setHasLoadedPersistentSettings] = useState(false);
  const [canSaveSettings, setCanSaveSettings] = useState(false);
  const [isLoadingSettings, setIsLoadingSettings] = useState(true);
  const [runtimeCapabilities, setRuntimeCapabilities] = useState<DsLlmRuntimeCapabilities>(() =>
    UNAVAILABLE_RUNTIME_CAPABILITIES,
  );
  const modelRequestIdRef = useRef(0);
  const isMountedRef = useRef(true);
  const settings = allSettings[profileKey] as FunctionalModelProfileSettingsMap[K];
  const usesSessionModel = "modelSource" in settings
    && settings.modelSource === "session";

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      modelRequestIdRef.current += 1;
    };
  }, []);

  useEffect(() => {
    let isStale = false;

    async function loadPersistentSettings() {
      setHasLoadedPersistentSettings(false);
      setCanSaveSettings(false);
      setIsLoadingSettings(true);
      try {
        const response = await getFunctionalModelProfileSettings(profileKey);
        if (isStale) return;
        setError(null);

        if (typeof response.version === "number" && response.version >= 1) {
          setSettingsVersion(response.version);
        }

        if (!response.default_settings) {
          throw new Error("后端没有返回功能模型默认设置。");
        }

        const defaultProfileSettings = normalizeProfileSettings(
          profileKey,
          response.default_settings,
          response.version,
        );
        if (response.has_settings && response.settings) {
          setAllSettings((current) => ({
            ...current,
            [profileKey]: normalizeProfileSettings(profileKey, response.settings, response.version),
          }));
          setCanSaveSettings(true);
          return;
        }

        setAllSettings((current) => ({
          ...current,
          [profileKey]: defaultProfileSettings,
        }));
        setCanSaveSettings(true);
      } catch (loadError) {
        if (isStale) return;

        setCanSaveSettings(false);
        setError(loadError instanceof Error ? loadError.message : "功能模型设置载入失败。");
      } finally {
        if (!isStale) {
          setHasLoadedPersistentSettings(true);
          setIsLoadingSettings(false);
        }
      }
    }

    void loadPersistentSettings();
    return () => {
      isStale = true;
    };
  }, [profileKey]);

  useQueuedFunctionalModelSettingsSave({
    canSaveSettings,
    hasLoadedPersistentSettings,
    onSaveError: setError,
    profileKey,
    settings,
    settingsVersion,
  });

  const reloadModels = useCallback(async (
    options: ReloadFunctionalModelsOptions = {},
  ) => {
    const requestId = modelRequestIdRef.current + 1;
    modelRequestIdRef.current = requestId;
    const shouldShowLoading = options.silent !== true;
    if (shouldShowLoading) {
      setIsLoadingModels(true);
    }
    setError(null);
    try {
      const response = await getModelCatalog({
        kind: getModelCatalogKind(profileKey),
      });
      if (!isMountedRef.current || modelRequestIdRef.current !== requestId) return;

      const nextModels = response.items.map(toFunctionalModelOption);
      setEligibleTextModels(nextModels);
      if (options.clearUnavailableSelection && !usesSessionModel) {
        clearUnavailableProfileModel(profileKey, nextModels, setAllSettings);
      }
    } catch (loadError) {
      if (!isMountedRef.current || modelRequestIdRef.current !== requestId) return;

      if (shouldShowLoading) {
        setEligibleTextModels([]);
      }
      setError(loadError instanceof Error ? loadError.message : "功能模型列表载入失败。");
    } finally {
      if (isMountedRef.current && modelRequestIdRef.current === requestId) {
        setIsLoadingModels(false);
      }
    }
  }, [profileKey, usesSessionModel]);

  useEffect(() => {
    void reloadModels();
  }, [reloadModels]);

  useEffect(() =>
    subscribeLlmModelCatalogChanged(() => {
      void reloadModels({ clearUnavailableSelection: true, silent: true });
    }), [reloadModels]);

  useEffect(() => {
    if (
      usesSessionModel
      || !hasLoadedPersistentSettings
      || isLoadingModels
      || error
      || !settings.modelKey
    ) {
      return;
    }

    if (eligibleTextModels.some((model) => getFunctionalModelKey(model) === settings.modelKey)) {
      return;
    }

    clearUnavailableProfileModel(profileKey, eligibleTextModels, setAllSettings);
  }, [
    eligibleTextModels,
    error,
    hasLoadedPersistentSettings,
    isLoadingModels,
    profileKey,
    settings.modelKey,
    usesSessionModel,
  ]);

  const selectedModel = useMemo(
    () =>
      eligibleTextModels.find((model) =>
        getFunctionalModelKey(model) === settings.modelKey,
      ) ?? null,
    [eligibleTextModels, settings.modelKey],
  );

  useEffect(() => {
    let isStale = false;

    if (usesSessionModel || !selectedModel) {
      setRuntimeCapabilities(UNAVAILABLE_RUNTIME_CAPABILITIES);
      setRuntimeCapabilitiesError(null);
      return () => {
        isStale = true;
      };
    }

    const providerId = selectedModel.providerId;
    const modelId = selectedModel.modelId;

    async function loadRuntimeCapabilities() {
      try {
        const capabilities = await getRuntimeCapabilities(providerId, modelId);
        if (!isStale) {
          setRuntimeCapabilities(capabilities);
          setRuntimeCapabilitiesError(null);
        }
      } catch (loadError) {
        if (!isStale) {
          setRuntimeCapabilities(UNAVAILABLE_RUNTIME_CAPABILITIES);
          setRuntimeCapabilitiesError(
            loadError instanceof Error ? loadError.message : "模型运行能力载入失败。",
          );
        }
      }
    }

    void loadRuntimeCapabilities();
    return () => {
      isStale = true;
    };
  }, [selectedModel, usesSessionModel]);

  useEffect(() => {
    setAllSettings((current) => {
      if (usesSessionModel || isRuntimeCapabilitiesUnavailable(runtimeCapabilities)) {
        return current;
      }

      const currentProfile = current[profileKey];
      const supportedOutputFormats = runtimeCapabilities.outputFormats;
      const nextOutputFormat = supportedOutputFormats.includes(currentProfile.output.format)
        ? currentProfile.output.format
        : supportedOutputFormats[0] ?? "text";

      const currentReasoningMode = currentProfile.generation.reasoning?.mode ?? "default";
      const nextReasoningMode = runtimeCapabilities.reasoning.supported
        ? runtimeCapabilities.reasoning.modes.includes(currentReasoningMode)
          ? currentReasoningMode
          : runtimeCapabilities.reasoning.modes[0] ?? "default"
        : "default";

      const maxOutputTokens = currentProfile.generation.maxOutputTokens;
      const nextMaxOutputTokens = runtimeCapabilities.maxOutputTokens.supported
        && typeof maxOutputTokens === "number"
        ? Math.max(runtimeCapabilities.maxOutputTokens.min, maxOutputTokens)
        : maxOutputTokens;

      const outputChanged = currentProfile.output.format !== nextOutputFormat;
      const reasoningChanged = currentReasoningMode !== nextReasoningMode;
      const maxTokensChanged = maxOutputTokens !== nextMaxOutputTokens;
      if (!outputChanged && !reasoningChanged && !maxTokensChanged) {
        return current;
      }

      return {
        ...current,
        [profileKey]: {
          ...currentProfile,
          generation: {
            ...currentProfile.generation,
            maxOutputTokens: nextMaxOutputTokens,
            reasoning: {
              ...(currentProfile.generation.reasoning ?? {}),
              mode: nextReasoningMode,
            },
          },
          output: {
            ...currentProfile.output,
            format: nextOutputFormat,
          },
        },
      };
    });
  }, [profileKey, runtimeCapabilities, usesSessionModel]);

  const updateProfileSetting = useCallback(
    <P extends keyof FunctionalModelProfileSettingsMap[K]>(
      key: P,
      value: FunctionalModelProfileSettingsMap[K][P],
    ) => {
      setAllSettings((current) => {
        const currentProfile = current[profileKey] as FunctionalModelProfileSettingsMap[K];
        if (currentProfile[key] === value) {
          return current;
        }

        return {
          ...current,
          [profileKey]: {
            ...currentProfile,
            [key]: value,
          },
        };
      });
    },
    [profileKey],
  );

  const updateGenerationParam = useCallback(
    <P extends keyof DsLlmGenerationParams>(
      key: P,
      value: DsLlmGenerationParams[P],
    ) => {
      setAllSettings((current) => {
        const currentProfile = current[profileKey];
        if (currentProfile.generation[key] === value) {
          return current;
        }

        return {
          ...current,
          [profileKey]: {
            ...currentProfile,
            generation: {
              ...currentProfile.generation,
              [key]: value,
            },
          },
        };
      });
    },
    [profileKey],
  );

  const updateOutputFormat = useCallback((format: DsLlmOutputFormat) => {
    setAllSettings((current) => {
      const currentProfile = current[profileKey];
      if (currentProfile.output.format === format) {
        return current;
      }

      return {
        ...current,
        [profileKey]: {
          ...currentProfile,
          output: {
            ...currentProfile.output,
            format,
          },
        },
      };
    });
  }, [profileKey]);

  const loadBackendDefaultSettings = useCallback(async () => {
    const response = await getFunctionalModelProfileSettings(profileKey);
    if (!response.default_settings) {
      throw new Error("后端没有返回功能模型默认设置。");
    }
    if (typeof response.version === "number" && response.version >= 1) {
      setSettingsVersion(response.version);
    }
    const defaultProfile = normalizeProfileSettings(
      profileKey,
      response.default_settings,
      response.version,
    );
    return defaultProfile;
  }, [profileKey]);

  const resetPrompt = useCallback(async (
    options: ResetFunctionalModelPromptOptions = {},
  ) => {
    try {
      setError(null);
      const defaultProfile = await loadBackendDefaultSettings();
      const promptKey = options.key ?? "prompt";
      const defaultPrompt = getStringSetting(defaultProfile, promptKey);
      if (defaultPrompt === null) {
        throw new Error("后端默认设置中没有对应提示词字段。");
      }

      setCanSaveSettings(true);
      setAllSettings((current) => {
        const currentProfile = current[profileKey];
        return {
          ...current,
          [profileKey]: {
            ...currentProfile,
            [promptKey]: defaultPrompt,
            ...(options.syncPromptKey ? { [options.syncPromptKey]: defaultPrompt } : {}),
          },
        };
      });
    } catch (resetError) {
      setError(resetError instanceof Error ? resetError.message : "提示词重置失败。");
    }
  }, [loadBackendDefaultSettings, profileKey]);

  const resetSettings = useCallback(async () => {
    try {
      setError(null);
      const defaultProfile = await loadBackendDefaultSettings();
      setCanSaveSettings(true);
      setAllSettings((current) => ({
        ...current,
        [profileKey]: defaultProfile,
      }));
    } catch (resetError) {
      setError(resetError instanceof Error ? resetError.message : "功能模型设置重置失败。");
    }
  }, [loadBackendDefaultSettings, profileKey]);

  return useMemo(() => ({
    eligibleTextModels,
    error: error ?? runtimeCapabilitiesError,
    isLoadingModels,
    isLoadingSettings,
    reloadModels,
    resetPrompt,
    resetSettings,
    runtimeCapabilities,
    selectedModel,
    settings,
    updateGenerationParam,
    updateOutputFormat,
    updateProfileSetting,
  }), [
    eligibleTextModels,
    error,
    isLoadingModels,
    isLoadingSettings,
    reloadModels,
    resetPrompt,
    resetSettings,
    runtimeCapabilities,
    runtimeCapabilitiesError,
    selectedModel,
    settings,
    updateGenerationParam,
    updateOutputFormat,
    updateProfileSetting,
  ]);
}
