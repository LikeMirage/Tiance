import { Check, Desktop } from "@phosphor-icons/react";
import { useEffect } from "react";

import { useLocaleSettings } from "../model/useLocaleSettings";
import { useI18n } from "../../../shared/i18n";

import "./language-settings.css";

type LanguageSettingsPanelProps = {
  onReady?: () => void;
};

export function LanguageSettingsPanel({ onReady }: LanguageSettingsPanelProps) {
  const { language, t } = useI18n();
  const localeSettings = useLocaleSettings();

  useEffect(() => {
    onReady?.();
  }, [onReady]);

  if (localeSettings.isLoading) {
    return (
      <div className="language-settings">
        <div className="language-settings__notice" role="status">
          {t("languageSettings.loading")}
        </div>
      </div>
    );
  }

  if (!localeSettings.settings) {
    return (
      <div className="language-settings">
        <div className="language-settings__notice language-settings__notice--error" role="alert">
          <span>{t("languageSettings.loadFailed")}</span>
          <button type="button" onClick={() => void localeSettings.reload()}>
            {t("languageSettings.retry")}
          </button>
        </div>
      </div>
    );
  }

  const selectedValue = localeSettings.settings.mode === "system"
    ? "system"
    : localeSettings.settings.activeLocale;

  return (
    <div className="language-settings">
      <header className="language-settings__head">
        <h2>{t("languageSettings.title")}</h2>
      </header>

      {localeSettings.error ? (
        <div className="language-settings__notice language-settings__notice--error" role="alert">
          <span>{t("languageSettings.saveFailed")}</span>
          <button type="button" onClick={() => void localeSettings.reload()}>
            {t("languageSettings.retry")}
          </button>
        </div>
      ) : null}

      <section className="language-settings__section" aria-label={t("languageSettings.selection") }>
        <button
          className={selectedValue === "system"
            ? "language-settings__option language-settings__option--active"
            : "language-settings__option"}
          type="button"
          disabled={localeSettings.isSaving}
          aria-pressed={selectedValue === "system"}
          onClick={() => void localeSettings.select("system", language)}
        >
          <Desktop size={20} aria-hidden="true" />
          <span className="language-settings__option-copy">
            <strong>{t("languageSettings.system")}</strong>
            <small>{t("languageSettings.systemDescription", { language: localeSettings.activeLocale })}</small>
          </span>
          {selectedValue === "system" ? <Check size={18} weight="bold" aria-hidden="true" /> : null}
        </button>

        <h3>{t("languageSettings.available")}</h3>
        <div className="language-settings__options">
          {localeSettings.locales.map((locale) => {
            const isSelected = selectedValue === locale.locale;
            return (
              <button
                key={locale.locale}
                className={isSelected
                  ? "language-settings__option language-settings__option--active"
                  : "language-settings__option"}
                type="button"
                disabled={localeSettings.isSaving}
                aria-pressed={isSelected}
                onClick={() => void localeSettings.select("manual", locale.locale)}
              >
                <span className="language-settings__locale-code">{locale.locale}</span>
                <span className="language-settings__option-copy">
                  <strong>{locale.displayName}</strong>
                  <small>{isSelected ? t("languageSettings.selected") : t("languageSettings.select")}</small>
                </span>
                {isSelected ? <Check size={18} weight="bold" aria-hidden="true" /> : null}
              </button>
            );
          })}
          {localeSettings.locales.length === 0 ? (
            <div className="language-settings__notice" role="status">
              {t("languageSettings.empty")}
            </div>
          ) : null}
        </div>
      </section>

      {localeSettings.isSaving ? (
        <div className="language-settings__saving" role="status">
          {t("languageSettings.switching")}
        </div>
      ) : null}
    </div>
  );
}
