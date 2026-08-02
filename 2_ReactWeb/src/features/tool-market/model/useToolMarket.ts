import { useCallback, useEffect, useRef, useState } from "react";

import { dispatchProjectCatalogChanged } from "../../../entities/project/model/projectCatalogEvents";
import {
  connectToolMarket,
  DEFAULT_TOOL_MARKET_SOURCE,
  getToolMarketIndex,
  getToolMarketSettings,
  installToolFromMarket,
  saveToolMarketFilters,
} from "../../../services/tools/toolMarketApi";
import { useOnlineMarketSource } from "../../../shared/online-market/useOnlineMarketSource";
import type { ToolMarketFilters, ToolMarketIndex } from "./toolMarket";

const EMPTY_FILTERS: ToolMarketFilters = {
  authors: [], platforms: [], runtimes: [], statuses: [],
};

export type ToolInstallState = {
  error: string | null;
  phase: "idle" | "installing" | "success" | "error";
};

export function useToolMarket(isActive: boolean, onInstalled?: () => void) {
  const [installStates, setInstallStates] = useState<Record<string, ToolInstallState>>({});
  const operationControllersRef = useRef(new Map<string, AbortController>());
  const { setIndex, ...market } = useOnlineMarketSource<ToolMarketIndex, ToolMarketFilters>({
    connectSource: connectToolMarket,
    defaultSource: DEFAULT_TOOL_MARKET_SOURCE,
    emptyFilters: EMPTY_FILTERS,
    indexErrorMessage: "在线工具读取失败。",
    isActive,
    loadIndex: getToolMarketIndex,
    loadSettings: getToolMarketSettings,
    saveFilters: saveToolMarketFilters,
    settingsErrorMessage: "在线工具设置读取失败。",
  });

  useEffect(() => () => {
    operationControllersRef.current.forEach((controller) => controller.abort());
    operationControllersRef.current.clear();
  }, []);

  const install = useCallback(async (
    toolId: string,
    categoryId: string | null,
    callName: string | null,
  ) => {
    if (operationControllersRef.current.has(toolId)) return false;
    const controller = new AbortController();
    operationControllersRef.current.set(toolId, controller);
    setInstallStates((current) => ({
      ...current, [toolId]: { error: null, phase: "installing" },
    }));
    try {
      const result = await installToolFromMarket(toolId, categoryId, callName, controller.signal);
      setIndex((current) => current ? {
        ...current,
        tools: current.tools.map((tool) => tool.id === result.toolId ? {
          ...tool,
          installationStatus: "installed" as const,
          localCallName: result.callName,
          localProjectId: result.projectId,
          localVersion: result.version,
          suggestedCallName: null,
        } : tool),
      } : current);
      setInstallStates((current) => ({
        ...current, [toolId]: { error: null, phase: "success" },
      }));
      dispatchProjectCatalogChanged();
      onInstalled?.();
      return true;
    } catch (installError) {
      if (controller.signal.aborted) return false;
      setInstallStates((current) => ({
        ...current,
        [toolId]: {
          error: installError instanceof Error ? installError.message : "工具安装失败。",
          phase: "error",
        },
      }));
      return false;
    } finally {
      operationControllersRef.current.delete(toolId);
    }
  }, [onInstalled]);

  return {
    ...market, install, installStates,
  };
}
