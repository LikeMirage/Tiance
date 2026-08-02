import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { subscribeLlmModelCatalogChanged } from "../../../entities/llm-provider/model/modelCatalogEvents";
import { getModelCatalog } from "../../../services/llm/getModelCatalog";
import { toChatModelOption, type ChatModelOption } from "./chatModelOption";

type ChatModelOptionsState = {
  error: string | null;
  isLoading: boolean;
  models: ChatModelOption[];
  reloadModels: (options?: ReloadChatModelsOptions) => Promise<void>;
  selectedModel: ChatModelOption | null;
  setSelectedModel: (model: ChatModelOption) => void;
};

type ReloadChatModelsOptions = {
  silent?: boolean;
};

export function useChatModelOptions(): ChatModelOptionsState {
  const [models, setModels] = useState<ChatModelOption[]>([]);
  const [selectedModelKey, setSelectedModelKey] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestIdRef = useRef(0);
  const isMountedRef = useRef(true);

  const reloadModels = useCallback(async (
    options: ReloadChatModelsOptions = {},
  ) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    const shouldShowLoading = options.silent !== true;
    if (shouldShowLoading) {
      setIsLoading(true);
    }
    setError(null);
    try {
      const response = await getModelCatalog({ kind: "chat" });

      if (!isMountedRef.current || requestIdRef.current !== requestId) return;

      const nextModels = response.items.map(toChatModelOption);
      setModels(nextModels);
      setSelectedModelKey((current) => {
        if (current && nextModels.some((model) => getModelKey(model) === current)) {
          return current;
        }
        return nextModels[0] ? getModelKey(nextModels[0]) : null;
      });
    } catch (err) {
      if (!isMountedRef.current || requestIdRef.current !== requestId) return;
      if (shouldShowLoading) {
        setModels([]);
        setSelectedModelKey(null);
      }
      setError(err instanceof Error ? err.message : "模型列表加载失败");
    } finally {
      if (isMountedRef.current && requestIdRef.current === requestId) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      requestIdRef.current += 1;
    };
  }, []);

  useEffect(() => {
    void reloadModels();
  }, [reloadModels]);

  useEffect(() =>
    subscribeLlmModelCatalogChanged(() => {
      void reloadModels({ silent: true });
    }), [reloadModels]);

  const selectedModel = useMemo(
    () => models.find((model) => getModelKey(model) === selectedModelKey) ?? null,
    [models, selectedModelKey],
  );

  return {
    error,
    isLoading,
    models,
    reloadModels,
    selectedModel,
    setSelectedModel: (model) => setSelectedModelKey(getModelKey(model)),
  };
}

export function getModelKey(model: ChatModelOption) {
  return `${model.providerId}:${model.modelId}`;
}
