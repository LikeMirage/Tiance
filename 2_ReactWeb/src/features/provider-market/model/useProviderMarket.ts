import { useCallback, useEffect, useRef, useState } from "react";

import { emitLlmModelCatalogChanged } from "../../../entities/llm-provider/model/modelCatalogEvents";
import { dispatchProjectCatalogChanged } from "../../../entities/project/model/projectCatalogEvents";
import {
  connectProviderMarket,
  DEFAULT_PROVIDER_MARKET_SOURCE,
  getProviderMarketIndex,
  getProviderMarketSettings,
  installProviderFromMarket,
  saveProviderMarketFilters,
} from "../../../services/llm/providerMarketApi";
import { useOnlineMarketSource } from "../../../shared/online-market/useOnlineMarketSource";
import type { ProviderMarketFilters, ProviderMarketIndex } from "./providerMarket";

const EMPTY_FILTERS: ProviderMarketFilters = { authors: [], protocols: [], statuses: [] };

export type ProviderInstallState = {
  error: string | null;
  phase: "idle" | "installing" | "success" | "error";
};

export function useProviderMarket(isActive: boolean) {
  const [installStates, setInstallStates] = useState<Record<string, ProviderInstallState>>({});
  const operationControllersRef = useRef(new Map<string, AbortController>());
  const { setIndex, ...market } = useOnlineMarketSource<
    ProviderMarketIndex,
    ProviderMarketFilters
  >({
    connectSource: connectProviderMarket,
    defaultSource: DEFAULT_PROVIDER_MARKET_SOURCE,
    emptyFilters: EMPTY_FILTERS,
    indexErrorMessage: "在线供应商读取失败。",
    isActive,
    loadIndex: getProviderMarketIndex,
    loadSettings: getProviderMarketSettings,
    saveFilters: saveProviderMarketFilters,
    settingsErrorMessage: "在线供应商设置读取失败。",
  });

  useEffect(() => () => {
    operationControllersRef.current.forEach((controller) => controller.abort());
    operationControllersRef.current.clear();
  }, []);

  const install = useCallback(async (
    providerId: string,
    categoryId: string | null,
    replaceExisting = false,
  ) => {
    if (operationControllersRef.current.has(providerId)) return false;
    const controller = new AbortController();
    operationControllersRef.current.set(providerId, controller);
    setInstallStates((current) => ({
      ...current,
      [providerId]: { error: null, phase: "installing" },
    }));
    try {
      const result = await installProviderFromMarket(
        providerId,
        categoryId,
        replaceExisting,
        controller.signal,
      );
      setIndex((current) => current ? {
        ...current,
        providers: current.providers.map((provider) => provider.id === result.providerId ? {
          ...provider,
          installationStatus: "installed" as const,
          localProjectId: result.projectId,
          localVersion: result.version,
        } : provider),
      } : current);
      setInstallStates((current) => ({
        ...current,
        [providerId]: { error: null, phase: "success" },
      }));
      dispatchProjectCatalogChanged();
      emitLlmModelCatalogChanged({ providerId });
      return true;
    } catch (installError) {
      if (controller.signal.aborted) return false;
      setInstallStates((current) => ({
        ...current,
        [providerId]: {
          error: installError instanceof Error ? installError.message : "供应商安装失败。",
          phase: "error",
        },
      }));
      return false;
    } finally {
      operationControllersRef.current.delete(providerId);
    }
  }, []);

  return {
    ...market, install, installStates,
  };
}
