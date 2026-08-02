import { useCallback, useEffect, useState } from "react";

import {
  getLocaleSettings,
  listLocales,
  type LocaleSelectionMode,
  type LocaleSettings,
  type LocaleSummary,
} from "../../../services/locale/localeSettings";
import { resolveSystemLanguage, useI18n } from "../../../shared/i18n";

type LocaleSettingsState = {
  activeLocale: string;
  error: string | null;
  isLoading: boolean;
  isSaving: boolean;
  locales: LocaleSummary[];
  settings: LocaleSettings | null;
};

const initialState: LocaleSettingsState = {
  activeLocale: "",
  error: null,
  isLoading: true,
  isSaving: false,
  locales: [],
  settings: null,
};

export function useLocaleSettings() {
  const { setLanguagePreference } = useI18n();
  const [state, setState] = useState<LocaleSettingsState>(initialState);

  const load = useCallback((signal?: AbortSignal) => {
    setState((current) => ({ ...current, error: null, isLoading: true }));
    return Promise.all([
      getLocaleSettings(signal),
      listLocales(resolveSystemLanguage(), signal),
    ])
      .then(([settings, catalog]) => {
        setState({
          activeLocale: catalog.activeLocale,
          error: null,
          isLoading: false,
          isSaving: false,
          locales: catalog.locales,
          settings,
        });
      })
      .catch((error: unknown) => {
        if (signal?.aborted) return;
        setState((current) => ({
          ...current,
          error: error instanceof Error ? error.message : String(error),
          isLoading: false,
        }));
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const select = useCallback(async (mode: LocaleSelectionMode, locale: string) => {
    if (!state.settings || state.isSaving) return;
    setState((current) => ({ ...current, error: null, isSaving: true }));
    try {
      const activeLocale = await setLanguagePreference(mode, locale);
      setState((current) => ({
        ...current,
        activeLocale,
        isSaving: false,
        settings: current.settings
          ? { ...current.settings, mode, activeLocale: locale }
          : current.settings,
      }));
    } catch (error) {
      setState((current) => ({
        ...current,
        error: error instanceof Error ? error.message : String(error),
        isSaving: false,
      }));
    }
  }, [setLanguagePreference, state.isSaving, state.settings]);

  return {
    ...state,
    reload: load,
    select,
  };
}
