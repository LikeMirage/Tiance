import type { ThemeMode, ThemeSummary } from "./themeTypes";

const APP_THEME_REFRESH_EVENT = "tiance:app-theme-refresh";

export type AppThemeRefreshReason = "theme_designer" | "theme_workspace";

export type AppThemeRefreshDetail = {
  reason: AppThemeRefreshReason;
  themeId?: string | null;
};

export interface AppThemeControl {
  activeThemeId: string | null;
  activeThemeName: string;
  mode: ThemeMode;
  isBootstrapping: boolean;
  isLoading: boolean;
  themes: ThemeSummary[];
  onOpenThemeMenu: () => void;
  onSelectTheme: (themeId: string) => void;
}

export function requestAppThemeRefresh(detail: AppThemeRefreshDetail): void {
  window.dispatchEvent(new CustomEvent<AppThemeRefreshDetail>(APP_THEME_REFRESH_EVENT, {
    detail,
  }));
}

export function subscribeAppThemeRefresh(
  listener: (detail: AppThemeRefreshDetail) => void,
): () => void {
  const handleRefresh = (event: Event) => {
    listener((event as CustomEvent<AppThemeRefreshDetail>).detail);
  };

  window.addEventListener(APP_THEME_REFRESH_EVENT, handleRefresh);
  return () => {
    window.removeEventListener(APP_THEME_REFRESH_EVENT, handleRefresh);
  };
}
