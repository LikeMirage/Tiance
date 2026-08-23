import { useEffect, useLayoutEffect, useRef, useState } from "react";

import type {
  ProviderCatalogEntry,
  ProviderProtocolFamily,
} from "../../../entities/llm-provider/model/providerCatalog";
import type { UseProviderConfigStateResult } from "../../provider-config/model/useProviderConfigState";
import type { UseProviderModelDiscoveryResult } from "../../provider-model-discovery/model/useProviderModelDiscovery";
import { checkProviderModel } from "../../../services/llm/checkProviderModel";
import { useI18n } from "../../../shared/i18n";
import {
  useProviderModelManagement,
  type ModelManagementMode,
} from "../../provider-model-management/model/useProviderModelManagement";
import type { ModelCheckState } from "../../provider-model-management/model/modelCheckState";

type ProviderModelModeTab = {
  id: ModelManagementMode;
  onClick: () => void;
};

export type ProviderCanvasControllerInput = {
  isActive?: boolean;
  onUpdateProviderProtocol: (
    providerId: string,
    protocolFamily: ProviderProtocolFamily,
  ) => Promise<void>;
  providerConfigState: UseProviderConfigStateResult;
  providerModelDiscovery: UseProviderModelDiscoveryResult;
  selectedProvider: ProviderCatalogEntry;
};

export function useProviderCanvasController({
  isActive = true,
  onUpdateProviderProtocol,
  providerConfigState,
  providerModelDiscovery,
  selectedProvider,
}: ProviderCanvasControllerInput) {
  const { t } = useI18n();
  const modelCheckResetTimersRef = useRef(new Map<string, number>());
  const selectedProviderDraft = providerConfigState.selectedDraft;
  const modelManagementPanel = useProviderModelManagement(selectedProvider.provider_id, { isActive });
  const apiKeyInputRefs = useRef(new Map<string, HTMLInputElement>());
  const apiKeyFocusSnapshotRef = useRef<{
    ids: string[];
    providerId: string | null;
  }>({
    ids: [],
    providerId: null,
  });
  const [testingModelIds, setTestingModelIds] = useState<string[]>([]);
  const [modelCheckStates, setModelCheckStates] = useState<Record<string, ModelCheckState>>({});
  const [providerProtocolError, setProviderProtocolError] = useState<string | null>(null);
  const hasAnyProviderApiKey =
    selectedProviderDraft !== null &&
    selectedProviderDraft.apiKeys.some(
      (apiKey) => apiKey.value.trim().length > 0 || apiKey.hasStoredApiKey,
    );

  const clearModelCheckResetTimer = (modelId: string) => {
    const timerId = modelCheckResetTimersRef.current.get(modelId);
    if (timerId === undefined) {
      return;
    }

    window.clearTimeout(timerId);
    modelCheckResetTimersRef.current.delete(modelId);
  };

  const scheduleModelCheckStateReset = (modelId: string) => {
    clearModelCheckResetTimer(modelId);
    const timerId = window.setTimeout(() => {
      setModelCheckStates((current) => {
        if (!(modelId in current)) {
          return current;
        }

        const next = { ...current };
        delete next[modelId];
        return next;
      });
      modelCheckResetTimersRef.current.delete(modelId);
    }, 1000);
    modelCheckResetTimersRef.current.set(modelId, timerId);
  };

  const clearAllModelCheckResetTimers = () => {
    modelCheckResetTimersRef.current.forEach((timerId) => {
      window.clearTimeout(timerId);
    });
    modelCheckResetTimersRef.current.clear();
  };

  useEffect(() => {
    clearAllModelCheckResetTimers();
    setProviderProtocolError(null);
    setModelCheckStates({});
    setTestingModelIds([]);
  }, [selectedProvider.provider_id]);

  useEffect(() => () => clearAllModelCheckResetTimers(), []);

  useLayoutEffect(() => {
    const providerId = selectedProvider.provider_id;
    const apiKeyIds = selectedProviderDraft?.apiKeys.map((apiKey) => apiKey.id) ?? [];
    const previousSnapshot = apiKeyFocusSnapshotRef.current;

    apiKeyFocusSnapshotRef.current = {
      ids: apiKeyIds,
      providerId,
    };

    if (previousSnapshot.providerId !== providerId) {
      return;
    }

    const addedApiKeyId = apiKeyIds.find(
      (apiKeyId) => !previousSnapshot.ids.includes(apiKeyId),
    );
    if (!addedApiKeyId) {
      return;
    }

    const animationFrameId = window.requestAnimationFrame(() => {
      apiKeyInputRefs.current.get(addedApiKeyId)?.focus();
    });

    return () => window.cancelAnimationFrame(animationFrameId);
  }, [selectedProvider.provider_id, selectedProviderDraft?.apiKeys]);

  const showCloudModelCatalog = () => {
    modelManagementPanel.selectCloudMode();

    void (async () => {
      const isSaved = await providerConfigState.saveSelectedProviderConfig();
      if (!isSaved) {
        return;
      }

      await providerModelDiscovery.loadSelectedModels({
        providerId: selectedProvider.provider_id,
      });
    })();
  };

  const updateSelectedProviderProtocol = async (
    protocolFamily: ProviderProtocolFamily,
  ) => {
    if (selectedProvider.protocol_family === protocolFamily) {
      return;
    }

    setProviderProtocolError(null);
    try {
      await onUpdateProviderProtocol(
        selectedProvider.provider_id,
        protocolFamily,
      );
    } catch (error) {
      setProviderProtocolError(
        error instanceof Error ? error.message : t("providerCanvas.errors.protocolUpdateFailed"),
      );
    }
  };

  const testModelConnection = async (modelId: string, label: string) => {
    clearModelCheckResetTimer(modelId);
    setTestingModelIds((current) =>
      current.includes(modelId) ? current : [...current, modelId],
    );
    setModelCheckStates((current) => {
      if (!(modelId in current)) {
        return current;
      }

      const next = { ...current };
      delete next[modelId];
      return next;
    });
    const isSaved = await providerConfigState.saveSelectedProviderConfig();
    if (!isSaved) {
      setModelCheckStates((current) => ({
        ...current,
        [modelId]: {
          message: t("providerCanvas.modelCheck.configSaveFailed", {
            model: label || modelId,
          }),
          tone: "error",
        },
      }));
      scheduleModelCheckStateReset(modelId);
      setTestingModelIds((current) => current.filter((item) => item !== modelId));
      return;
    }

    try {
      const result = await checkProviderModel(selectedProvider.provider_id, modelId);
      setModelCheckStates((current) => ({
        ...current,
        [modelId]: {
          message: t("providerCanvas.modelCheck.passed", {
            key: result.selected_api_key_hint
              ?? result.selected_key_id
              ?? t("providerCanvas.modelCheck.currentKey"),
            model: label || result.model_id,
          }),
          tone: "success",
        },
      }));
      scheduleModelCheckStateReset(modelId);
    } catch (error) {
      setModelCheckStates((current) => ({
        ...current,
        [modelId]: {
          message:
            error instanceof Error
              ? `${label || modelId}：${error.message}`
              : t("providerCanvas.modelCheck.testFailed", {
                model: label || modelId,
              }),
          tone: "error",
        },
      }));
      scheduleModelCheckStateReset(modelId);
    } finally {
      setTestingModelIds((current) => current.filter((item) => item !== modelId));
    }
  };

  const modelModeTabs: ProviderModelModeTab[] = [
    {
      id: "added",
      onClick: modelManagementPanel.selectAddedMode,
    },
    {
      id: "custom",
      onClick: modelManagementPanel.selectCustomMode,
    },
    {
      id: "cloud",
      onClick: showCloudModelCatalog,
    },
  ];
  return {
    apiKeyInputRefs,
    hasAnyProviderApiKey,
    modelCheckStates,
    modelManagementPanel,
    modelModeTabs,
    providerProtocolError,
    selectedProviderDraft,
    testModelConnection,
    testingModelIds,
    updateSelectedProviderProtocol,
  };
}
