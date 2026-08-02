import { useCallback, useState } from "react";

import { dispatchProjectCatalogChanged } from "../../../entities/project/model/projectCatalogEvents";
import {
  connectThemeMarket,
  DEFAULT_THEME_MARKET_SOURCE,
  getThemeMarketIndex,
  getThemeMarketSettings,
  installThemeFromMarket,
  saveThemeMarketFilters,
} from "../../../services/theme-market/themeMarketApi";
import { useOnlineMarketSource } from "../../../shared/online-market/useOnlineMarketSource";
import type {
  ThemeMarketFilters,
  ThemeMarketIndex,
} from "./themeMarket";

const EMPTY_FILTERS: ThemeMarketFilters = {
  authors: [],
  baseColors: [],
  modes: [],
  statuses: [],
};

export type ThemeInstallState = {
  error: string | null;
  phase: "idle" | "installing" | "success" | "error";
};

export function useThemeMarket(isActive: boolean) {
  const [installStates, setInstallStates] = useState<Record<string, ThemeInstallState>>({});
  const { setIndex, ...market } = useOnlineMarketSource<ThemeMarketIndex, ThemeMarketFilters>({
    connectSource: connectThemeMarket,
    defaultSource: DEFAULT_THEME_MARKET_SOURCE,
    emptyFilters: EMPTY_FILTERS,
    indexErrorMessage: "在线主题读取失败。",
    isActive,
    loadIndex: getThemeMarketIndex,
    loadSettings: getThemeMarketSettings,
    saveFilters: saveThemeMarketFilters,
    settingsErrorMessage: "在线主题设置读取失败。",
  });

  const install = useCallback(async (
    themeId: string,
    categoryId: string | null,
    replaceExisting = false,
  ) => {
    setInstallStates((current) => ({
      ...current,
      [themeId]: { error: null, phase: "installing" },
    }));
    try {
      const result = await installThemeFromMarket(themeId, categoryId, replaceExisting);
      setIndex((current) => current ? {
        ...current,
        themes: current.themes.map((theme) => theme.id === themeId ? {
          ...theme,
          installationStatus: "installed",
          localVersion: result.version,
        } : theme),
      } : current);
      setInstallStates((current) => ({
        ...current,
        [themeId]: { error: null, phase: "success" },
      }));
      dispatchProjectCatalogChanged();
      return true;
    } catch (installError) {
      setInstallStates((current) => ({
        ...current,
        [themeId]: {
          error: installError instanceof Error ? installError.message : "主题安装失败。",
          phase: "error",
        },
      }));
      return false;
    }
  }, []);

  return {
    ...market,
    install,
    installStates,
  };
}
