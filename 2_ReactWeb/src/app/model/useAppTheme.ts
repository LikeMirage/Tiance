import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getActiveThemeWithTimeout,
  listThemes,
  setActiveTheme,
  watchThemeWorkspaceEvents,
} from "../../services/theme";
import {
  applyTheme,
  requestAppThemeRefresh,
  subscribeAppThemeRefresh,
  type AppThemeControl,
  type ThemeDefinition,
  type ThemeSummary,
} from "../../shared/theme";

type UseAppThemeOptions = {
  initialTheme: ThemeDefinition | null;
  loadOnMount: boolean;
};

export function useAppTheme({
  initialTheme,
  loadOnMount,
}: UseAppThemeOptions): AppThemeControl {
  const shouldLoadInitialTheme = loadOnMount && initialTheme === null;
  const [theme, setTheme] = useState<ThemeDefinition | null>(initialTheme);
  const [themes, setThemes] = useState<ThemeSummary[]>(
    initialTheme ? [themeToSummary(initialTheme)] : [],
  );
  const [isBootstrapping, setIsBootstrapping] = useState(shouldLoadInitialTheme);
  const [isLoading, setIsLoading] = useState(shouldLoadInitialTheme);
  const refreshRequestIdRef = useRef(0);

  useEffect(() => {
    if (!shouldLoadInitialTheme) {
      return;
    }

    let isStale = false;

    setIsLoading(true);
    void loadInitialTheme()
      .then((loadedTheme) => {
        if (isStale) return;
        applyLoadedTheme(loadedTheme);
      })
      .catch((error) => {
        console.warn("Failed to initialize app theme.", error);
      })
      .finally(() => {
        if (!isStale) {
          setIsLoading(false);
          setIsBootstrapping(false);
        }
      });

    return () => {
      isStale = true;
    };
  }, [shouldLoadInitialTheme]);

  const loadThemeList = useCallback(() => {
    void listThemes()
      .then((response) => {
        setThemes(response.themes);
      })
      .catch((error) => {
        console.warn("Failed to load theme list.", error);
      });
  }, []);

  useEffect(() => {
    loadThemeList();
  }, [loadThemeList]);

  const refreshActiveTheme = useCallback(() => {
    const requestId = refreshRequestIdRef.current + 1;
    refreshRequestIdRef.current = requestId;
    setIsLoading(true);
    void getActiveThemeWithTimeout()
      .then((nextTheme) => {
        if (refreshRequestIdRef.current !== requestId) return;
        applyLoadedTheme(nextTheme);
      })
      .catch((error) => {
        console.warn("Failed to refresh app theme.", error);
      })
      .finally(() => {
        if (refreshRequestIdRef.current === requestId) {
          setIsLoading(false);
        }
      });
  }, []);

  useEffect(() => subscribeAppThemeRefresh((detail) => {
    refreshActiveTheme();
    if (detail.reason === "theme_workspace") loadThemeList();
  }), [loadThemeList, refreshActiveTheme]);

  useEffect(() => watchThemeWorkspaceEvents(() => {
    requestAppThemeRefresh({ reason: "theme_workspace" });
  }), []);

  const selectTheme = useCallback((themeId: string) => {
    if (isLoading || theme?.id === themeId) return;
    setIsLoading(true);
    void setActiveTheme(themeId)
      .then((nextTheme) => {
        applyLoadedTheme(nextTheme);
      })
      .catch((error) => {
        console.warn("Failed to switch app theme.", error);
      })
      .finally(() => setIsLoading(false));
  }, [isLoading, theme?.id]);

  const activeThemeName =
    theme?.name ??
    themes.find((themeSummary) => themeSummary.id === theme?.id)?.name ??
    "主题";

  return useMemo(
    () => ({
      activeThemeId: theme?.id ?? null,
      activeThemeName,
      mode: theme?.mode ?? "dark",
      isBootstrapping,
      isLoading,
      themes,
      onOpenThemeMenu: loadThemeList,
      onSelectTheme: selectTheme,
    }),
    [
      activeThemeName,
      isBootstrapping,
      isLoading,
      loadThemeList,
      selectTheme,
      themes,
      theme?.id,
      theme?.mode,
    ],
  );

  function applyLoadedTheme(nextTheme: ThemeDefinition) {
    applyTheme(nextTheme);
    setTheme(nextTheme);
    setThemes((current) => mergeThemeSummary(current, themeToSummary(nextTheme)));
  }
}

async function loadInitialTheme(): Promise<ThemeDefinition> {
  return getActiveThemeWithTimeout();
}

function themeToSummary(theme: ThemeDefinition): ThemeSummary {
  return {
    id: theme.id,
    mode: theme.mode,
    name: theme.name,
  };
}

function mergeThemeSummary(themes: ThemeSummary[], theme: ThemeSummary): ThemeSummary[] {
  if (themes.some((item) => item.id === theme.id)) {
    return themes.map((item) => (item.id === theme.id ? theme : item));
  }
  return [...themes, theme];
}
