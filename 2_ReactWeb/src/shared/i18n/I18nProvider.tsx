import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { getActiveLocale } from "../../services/locale/getActiveLocale";
import {
  type LocaleSelectionMode,
  updateLocaleSettings,
} from "../../services/locale/localeSettings";
import {
  builtinLocalePackages,
  dictionaries,
  isSupportedLanguage,
  type LocaleDirection,
  type TranslationDictionary,
  type TranslationKey,
} from "./locales";
import { DEFAULT_LANGUAGE, resolveSystemLanguage } from "./language";

type TranslationParams = Record<string, string | number>;

type I18nContextValue = {
  language: string;
  setLanguagePreference: (
    mode: LocaleSelectionMode,
    activeLocale: string,
  ) => Promise<string>;
  t: (key: TranslationKey, params?: TranslationParams) => string;
};

type LoadedDictionary = {
  dictionary: TranslationDictionary;
  direction: LocaleDirection;
  language: string;
};

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: PropsWithChildren) {
  const [loadedDictionary, setLoadedDictionary] = useState<LoadedDictionary | null>(null);

  useEffect(() => {
    let isMounted = true;
    const preferredLanguage = resolveSystemLanguage();

    void getActiveLocale(preferredLanguage)
      .then((locale) => {
        if (!isMounted) {
          return;
        }

        setLoadedDictionary({
          dictionary: locale.messages,
          direction: locale.direction,
          language: locale.locale,
        });
      })
      .catch((error) => {
        console.warn("Failed to load locale from Data/locales.", error);
        if (!isMounted) {
          return;
        }

        setLoadedDictionary(resolveBuiltinFallback(preferredLanguage));
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const dictionary = loadedDictionary?.dictionary ?? null;
  const direction = loadedDictionary?.direction ?? null;
  const language = loadedDictionary?.language ?? null;
  const fallbackLanguage = language && isSupportedLanguage(language)
    ? language
    : DEFAULT_LANGUAGE;

  const setLanguagePreference = useCallback<I18nContextValue["setLanguagePreference"]>(
    async (mode, activeLocale) => {
      await updateLocaleSettings(mode, activeLocale);
      const locale = await getActiveLocale(resolveSystemLanguage());
      setLoadedDictionary({
        dictionary: locale.messages,
        direction: locale.direction,
        language: locale.locale,
      });
      return locale.locale;
    },
    [],
  );

  const t = useCallback<I18nContextValue["t"]>(
    (key, params) => formatTranslation(
      readTranslation(dictionary, key)
        ?? readTranslation(dictionaries[fallbackLanguage], key)
        ?? key,
      params,
    ),
    [dictionary, fallbackLanguage],
  );

  useEffect(() => {
    if (!language) {
      return;
    }

    document.documentElement.lang = language;
    document.documentElement.dir = direction ?? "ltr";
    document.title = t("common.documentTitle");
  }, [direction, language, t]);

  const value = useMemo<I18nContextValue | null>(() => {
    if (!language || !dictionary) {
      return null;
    }

    return { language, setLanguagePreference, t };
  }, [dictionary, language, setLanguagePreference, t]);

  if (!value) {
    return null;
  }

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error("useI18n must be used inside I18nProvider.");
  }

  return context;
}

function readTranslation(dictionary: unknown, key: TranslationKey): string | undefined {
  const value = key.split(".").reduce<unknown>((current, part) => {
    if (!current || typeof current !== "object") {
      return undefined;
    }

    return (current as Record<string, unknown>)[part];
  }, dictionary);

  return typeof value === "string" ? value : undefined;
}

function formatTranslation(template: string, params: TranslationParams | undefined) {
  if (!params) {
    return template;
  }

  return template.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, key) => {
    const value = params[key];
    return value === undefined ? match : String(value);
  });
}

function resolveBuiltinFallback(preferredLanguage: string): LoadedDictionary {
  const language = isSupportedLanguage(preferredLanguage) ? preferredLanguage : DEFAULT_LANGUAGE;
  return {
    dictionary: dictionaries[language],
    direction: builtinLocalePackages[language].direction,
    language,
  };
}
