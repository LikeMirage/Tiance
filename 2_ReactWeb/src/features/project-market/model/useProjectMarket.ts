import { useCallback, useEffect, useRef, useState } from "react";

import { dispatchProjectCatalogChanged } from "../../../entities/project/model/projectCatalogEvents";
import {
  connectProjectMarket,
  getProjectMarketIndex,
  getProjectMarketInstallOperation,
  getProjectMarketSettings,
  getDefaultProjectMarketSource,
  restoreDefaultProjectMarket,
  saveProjectMarketFilters,
  startProjectMarketInstall,
} from "../../../services/project-market/projectMarketApi";
import { useOnlineMarketSource } from "../../../shared/online-market/useOnlineMarketSource";
import type {
  ProjectMarketFilters,
  ProjectMarketIndex,
  ProjectMarketInstallOperation,
  ProjectMarketScope,
} from "./projectMarket";

const EMPTY_FILTERS: ProjectMarketFilters = { authors: [], statuses: [], tags: [] };

export function useProjectMarket(isActive: boolean, scope: ProjectMarketScope) {
  const [installOperations, setInstallOperations] = useState<
    Record<string, ProjectMarketInstallOperation>
  >({});
  const installControllersRef = useRef(new Map<string, AbortController>());
  const { setIndex, ...market } = useOnlineMarketSource<
    ProjectMarketIndex,
    ProjectMarketFilters
  >({
    connectSource: (source, signal) => connectProjectMarket(scope, source, signal),
    defaultSource: getDefaultProjectMarketSource(scope),
    emptyFilters: EMPTY_FILTERS,
    indexErrorMessage: "在线项目读取失败。",
    isActive,
    loadIndex: (signal) => getProjectMarketIndex(scope, signal),
    loadSettings: (signal) => getProjectMarketSettings(scope, signal),
    resetSource: (signal) => restoreDefaultProjectMarket(scope, signal),
    saveFilters: (filters, signal) => saveProjectMarketFilters(scope, filters, signal),
    settingsErrorMessage: "在线项目设置读取失败。",
    sourceKey: scope,
  });

  useEffect(() => () => {
    for (const controller of installControllersRef.current.values()) controller.abort();
    installControllersRef.current.clear();
  }, []);

  const install = useCallback(async (marketProjectId: string, categoryId: string) => {
    if (installControllersRef.current.has(marketProjectId)) return false;
    const controller = new AbortController();
    installControllersRef.current.set(marketProjectId, controller);
    try {
      let operation = await startProjectMarketInstall(
        scope,
        marketProjectId,
        categoryId,
        controller.signal,
      );
      setInstallOperations((current) => ({ ...current, [marketProjectId]: operation }));
      while (operation.phase !== "completed" && operation.phase !== "failed") {
        await waitForPoll(controller.signal);
        operation = await getProjectMarketInstallOperation(
          scope,
          operation.operationId,
          controller.signal,
        );
        setInstallOperations((current) => ({ ...current, [marketProjectId]: operation }));
      }
      if (operation.phase === "failed" || !operation.result) return false;
      setIndex((current) => current ? {
        ...current,
        projects: current.projects.map((project) => project.id === marketProjectId ? {
          ...project,
          installationStatus: "installed",
          localProjectId: operation.result?.projectId ?? null,
        } : project),
      } : current);
      dispatchProjectCatalogChanged();
      return true;
    } catch (installError) {
      if (!controller.signal.aborted) {
        setInstallOperations((current) => ({
          ...current,
          [marketProjectId]: {
            error: installError instanceof Error ? installError.message : "项目安装失败。",
            marketProjectId,
            operationId: current[marketProjectId]?.operationId ?? "",
            phase: "failed",
            result: null,
          },
        }));
      }
      return false;
    } finally {
      installControllersRef.current.delete(marketProjectId);
    }
  }, [scope]);

  return {
    ...market,
    install,
    installOperations,
  };
}

function waitForPoll(signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      window.clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, 350);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}
