import { useCallback, useEffect, useRef, useState } from "react";

import { dispatchProjectCatalogChanged } from "../../../entities/project/model/projectCatalogEvents";
import {
  connectRoleMarket,
  DEFAULT_ROLE_MARKET_SOURCE,
  getRoleMarketIndex,
  getRoleMarketSettings,
  installRoleFromMarket,
  saveRoleMarketFilters,
} from "../../../services/role-market/roleMarketApi";
import { useOnlineMarketSource } from "../../../shared/online-market/useOnlineMarketSource";
import type { RoleMarketFilters, RoleMarketIndex } from "./roleMarket";
import { applyInstalledRoleResult } from "./roleMarketOperations";

const EMPTY_FILTERS: RoleMarketFilters = { authors: [], statuses: [] };

export type RoleInstallState = {
  error: string | null;
  phase: "idle" | "installing" | "success" | "error";
};

export function useRoleMarket(isActive: boolean) {
  const [installStates, setInstallStates] = useState<Record<string, RoleInstallState>>({});
  const operationControllersRef = useRef(new Map<string, AbortController>());
  const { setIndex, ...market } = useOnlineMarketSource<RoleMarketIndex, RoleMarketFilters>({
    connectSource: connectRoleMarket,
    defaultSource: DEFAULT_ROLE_MARKET_SOURCE,
    emptyFilters: EMPTY_FILTERS,
    indexErrorMessage: "在线角色读取失败。",
    isActive,
    loadIndex: getRoleMarketIndex,
    loadSettings: getRoleMarketSettings,
    saveFilters: saveRoleMarketFilters,
    settingsErrorMessage: "在线角色设置读取失败。",
  });

  useEffect(() => () => {
    operationControllersRef.current.forEach((controller) => controller.abort());
    operationControllersRef.current.clear();
  }, []);

  const install = useCallback(async (
    roleId: string,
    categoryId: string | null,
    replaceExisting = false,
  ) => {
    if (operationControllersRef.current.has(roleId)) return false;
    const controller = new AbortController();
    operationControllersRef.current.set(roleId, controller);
    setInstallStates((current) => ({
      ...current,
      [roleId]: { error: null, phase: "installing" },
    }));
    try {
      const result = await installRoleFromMarket(
        roleId,
        categoryId,
        replaceExisting,
        controller.signal,
      );
      setIndex((current) => current ? {
        ...current,
        roles: applyInstalledRoleResult(current.roles, result),
      } : current);
      setInstallStates((current) => ({
        ...current,
        [roleId]: { error: null, phase: "success" },
      }));
      dispatchProjectCatalogChanged();
      return true;
    } catch (installError) {
      if (controller.signal.aborted) return false;
      setInstallStates((current) => ({
        ...current,
        [roleId]: {
          error: installError instanceof Error ? installError.message : "角色安装失败。",
          phase: "error",
        },
      }));
      return false;
    } finally {
      operationControllersRef.current.delete(roleId);
    }
  }, []);

  return {
    ...market,
    install,
    installStates,
  };
}
