import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getTheme, listThemes, updateTheme } from "../../../services/theme";
import { useI18n, type TranslationKey } from "../../../shared/i18n";
import { OptionSelect, type OptionSelectItem } from "../../../shared/ui/option-select/OptionSelect";
import {
  requestAppThemeRefresh,
  subscribeAppThemeRefresh,
  type ThemeDefinition,
  type ThemeSummary,
} from "../../../shared/theme";
import {
  THEME_INFO_FIELD_GROUP,
  THEME_SETTINGS_SECTIONS,
  type ThemeFieldConfig,
  type ThemeFieldGroup,
  type ThemeSettingsSectionId,
} from "../model/themeSettingsFields";
import {
  applyColorPickerValue,
  toColorPickerValue,
} from "../model/themeColorValue";

import "./theme-settings.css";

const THEME_AUTO_SAVE_DELAY_MS = 450;

type ThemeSettingsPanelProps = {
  activeThemeId: string | null;
  onReady?: () => void;
  themeId?: string | null;
};

export function ThemeSettingsPanel({
  activeThemeId,
  onReady,
  themeId,
}: ThemeSettingsPanelProps) {
  const { t } = useI18n();
  const [themes, setThemes] = useState<ThemeSummary[]>([]);
  const [catalogActiveThemeId, setCatalogActiveThemeId] = useState<string | null>(null);
  const [selectedThemeId, setSelectedThemeId] = useState<string | null>(
    themeId ?? activeThemeId,
  );
  const [loadedTheme, setLoadedTheme] = useState<ThemeDefinition | null>(null);
  const [draftTheme, setDraftTheme] = useState<ThemeDefinition | null>(null);
  const [activeSectionId, setActiveSectionId] =
    useState<ThemeSettingsSectionId>(THEME_SETTINGS_SECTIONS[0].id);
  const [isLoading, setIsLoading] = useState(true);
  const [isThemeCatalogLoading, setIsThemeCatalogLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadRequestIdRef = useRef(0);
  const saveRequestIdRef = useRef(0);
  const externalLoadRequestIdRef = useRef(0);
  const externalRefreshStateRef = useRef({
    isDirty: false,
    isLoading: true,
    isSaving: false,
    selectedThemeId: selectedThemeId as string | null,
  });

  const loadedFingerprint = useMemo(
    () => loadedTheme ? fingerprintTheme(loadedTheme) : "",
    [loadedTheme],
  );
  const draftFingerprint = useMemo(
    () => draftTheme ? fingerprintTheme(draftTheme) : "",
    [draftTheme],
  );
  const isDirty = loadedTheme !== null && draftTheme !== null &&
    draftFingerprint !== loadedFingerprint;
  externalRefreshStateRef.current = {
    isDirty,
    isLoading,
    isSaving,
    selectedThemeId,
  };
  const currentActiveThemeId = activeThemeId ?? catalogActiveThemeId;
  const activeSection = useMemo(
    () =>
      THEME_SETTINGS_SECTIONS.find((section) => section.id === activeSectionId) ??
      THEME_SETTINGS_SECTIONS[0],
    [activeSectionId],
  );
  const themeOptions = useMemo<Array<OptionSelectItem<string>>>(
    () => themes.map((theme) => ({
      label: theme.name,
      value: theme.id,
    })),
    [themes],
  );

  useEffect(() => {
    let isStale = false;
    setIsThemeCatalogLoading(true);

    void listThemes()
      .then((response) => {
        if (isStale) return;
        setThemes(response.themes);
        setCatalogActiveThemeId(response.active_theme_id);
        setSelectedThemeId((current) =>
          themeId
            ?? current
            ?? activeThemeId
            ?? response.active_theme_id
            ?? response.themes[0]?.id
            ?? null,
        );
      })
      .catch((loadError) => {
        if (isStale) return;
        setError(loadError instanceof Error ? loadError.message : t("themeSettings.errors.loadListFailed"));
      })
      .finally(() => {
        if (isStale) return;
        setIsThemeCatalogLoading(false);
      });

    return () => {
      isStale = true;
    };
  }, [activeThemeId, t, themeId]);

  useEffect(() => {
    if (themeId !== undefined) {
      setSelectedThemeId(themeId);
    }
  }, [themeId]);

  useEffect(() => subscribeAppThemeRefresh((detail) => {
    if (detail.reason !== "theme_workspace") return;
    const current = externalRefreshStateRef.current;
    if (
      !current.selectedThemeId
      || current.isDirty
      || current.isLoading
      || current.isSaving
    ) return;

    const requestId = externalLoadRequestIdRef.current + 1;
    externalLoadRequestIdRef.current = requestId;
    void getTheme(current.selectedThemeId)
      .then((nextTheme) => {
        const latest = externalRefreshStateRef.current;
        if (
          externalLoadRequestIdRef.current !== requestId
          || latest.selectedThemeId !== current.selectedThemeId
          || latest.isDirty
          || latest.isLoading
          || latest.isSaving
        ) return;
        setLoadedTheme(nextTheme);
        setDraftTheme(nextTheme);
        setThemes((themes) => mergeThemeSummary(themes, nextTheme));
        setError(null);
      })
      .catch(() => {
        // 外部写入可能短暂处于不完整状态；保留最后一次有效配置等待下次文件事件。
      });
  }), []);

  useEffect(() => {
    if (!selectedThemeId) {
      externalLoadRequestIdRef.current += 1;
      setLoadedTheme(null);
      setDraftTheme(null);
      setIsLoading(false);
      return;
    }

    const requestId = loadRequestIdRef.current + 1;
    loadRequestIdRef.current = requestId;
    externalLoadRequestIdRef.current += 1;
    setIsLoading(true);

    void getTheme(selectedThemeId)
      .then((theme) => {
        if (loadRequestIdRef.current !== requestId) return;
        setLoadedTheme(theme);
        setDraftTheme(theme);
        setError(null);
      })
      .catch((loadError) => {
        if (loadRequestIdRef.current !== requestId) return;
        setLoadedTheme(null);
        setDraftTheme(null);
        setError(loadError instanceof Error ? loadError.message : t("themeSettings.errors.loadFailed"));
      })
      .finally(() => {
        if (loadRequestIdRef.current === requestId) {
          setIsLoading(false);
        }
      });
  }, [selectedThemeId, t]);

  const handleSelectTheme = useCallback((themeId: string) => {
    if (themeId === selectedThemeId) return;
    setError(null);
    setSelectedThemeId(themeId);
  }, [selectedThemeId]);

  useEffect(() => {
    if (!selectedThemeId || !draftTheme || !isDirty || isLoading) {
      return;
    }

    if (draftTheme.id !== selectedThemeId) {
      setError(t("themeSettings.errors.idMismatch"));
      return;
    }

    const requestId = saveRequestIdRef.current + 1;
    const savingFingerprint = draftFingerprint;
    const savingTheme = draftTheme;
    saveRequestIdRef.current = requestId;
    setIsSaving(true);
    setError(null);

    const timerId = window.setTimeout(() => {
      void updateTheme(selectedThemeId, savingTheme)
        .then((savedTheme) => {
          if (saveRequestIdRef.current !== requestId) return;
          setLoadedTheme(savedTheme);
          setDraftTheme((current) =>
            current && fingerprintTheme(current) !== savingFingerprint
              ? current
              : savedTheme,
          );
          setThemes((current) => mergeThemeSummary(current, savedTheme));
          if (savedTheme.id === currentActiveThemeId) {
            requestAppThemeRefresh({ reason: "theme_designer", themeId: savedTheme.id });
          }
        })
        .catch((saveError) => {
          if (saveRequestIdRef.current !== requestId) return;
          setError(saveError instanceof Error ? saveError.message : t("themeSettings.errors.saveFailed"));
        })
        .finally(() => {
          if (saveRequestIdRef.current === requestId) {
            setIsSaving(false);
          }
        });
    }, THEME_AUTO_SAVE_DELAY_MS);

    return () => {
      window.clearTimeout(timerId);
    };
  }, [
    currentActiveThemeId,
    draftFingerprint,
    draftTheme,
    isDirty,
    isLoading,
    selectedThemeId,
    t,
  ]);

  useEffect(() => {
    if (isThemeCatalogLoading) return;
    if (draftTheme || error || (!isLoading && !selectedThemeId)) {
      onReady?.();
    }
  }, [draftTheme, error, isLoading, isThemeCatalogLoading, onReady, selectedThemeId]);

  const handleFieldChange = useCallback((field: ThemeFieldConfig, rawValue: string) => {
    setError(null);
    setDraftTheme((current) => {
      if (!current || field.readOnly) return current;
      return setThemePathValue(
        current,
        field.path,
        parseFieldInputValue(field, rawValue),
      );
    });
  }, []);

  return (
    <div className="theme-settings">
      <section className="theme-settings__section" aria-label={t("themeSettings.title")}>
        <header className="theme-settings__head">
          <div className="theme-settings__heading">
            <h2 className="theme-settings__title">{t("themeSettings.title")}</h2>
          </div>

          {themeId === undefined ? (
            <label className="theme-settings__field theme-settings__field--select theme-settings__theme-file-field">
              <OptionSelect
                ariaLabel={t("themeSettings.themeFile")}
                className="theme-settings__option-select theme-settings__theme-file-select"
                value={selectedThemeId ?? ""}
                disabled={isThemeCatalogLoading || isLoading || isSaving || themeOptions.length === 0}
                floating
                options={themeOptions}
                placeholder={t("themeSettings.selectThemeFile")}
                showSelectedOption
                onChange={handleSelectTheme}
              />
            </label>
          ) : null}
        </header>

        {error ? (
          <div className="theme-settings__error" role="alert">
            {error}
          </div>
        ) : null}

        {draftTheme ? (
          <div className="theme-settings__groups">
            <ThemeFieldGroupView
              disabled={isLoading}
              group={THEME_INFO_FIELD_GROUP}
              theme={draftTheme}
              onChange={handleFieldChange}
            />

            <section className="theme-settings__section-group" aria-label={t("themeSettings.params")}>
              <header className="theme-settings__section-head">
                <h3 className="theme-settings__group-title">{t("themeSettings.params")}</h3>
                <div
                  className="theme-settings__section-tabs"
                  role="tablist"
                  aria-label={t("themeSettings.paramCategories")}
                >
                  {THEME_SETTINGS_SECTIONS.map((section) => (
                    <button
                      key={section.id}
                      id={`theme-settings-tab-${section.id}`}
                      className={
                        activeSection.id === section.id
                          ? "theme-settings__section-tab theme-settings__section-tab--active"
                          : "theme-settings__section-tab"
                      }
                      type="button"
                      role="tab"
                      aria-controls={`theme-settings-panel-${section.id}`}
                      aria-selected={activeSection.id === section.id}
                      onClick={() => setActiveSectionId(section.id)}
                    >
                      {t(section.labelKey)}
                    </button>
                  ))}
                </div>
              </header>

              <div
                id={`theme-settings-panel-${activeSection.id}`}
                className="theme-settings__section-body"
                role="tabpanel"
                aria-labelledby={`theme-settings-tab-${activeSection.id}`}
              >
                {activeSection.groups.map((group) => (
                  <ThemeFieldGroupView
                    key={group.id}
                    disabled={isLoading}
                    group={group}
                    theme={draftTheme}
                    onChange={handleFieldChange}
                  />
                ))}
              </div>
            </section>
          </div>
        ) : isThemeCatalogLoading || isLoading || selectedThemeId ? null : (
          <div className="theme-settings__empty" role="status">
            {t("themeSettings.empty")}
          </div>
        )}
      </section>
    </div>
  );
}

function ThemeFieldGroupView({
  disabled,
  group,
  theme,
  onChange,
}: {
  disabled: boolean;
  group: ThemeFieldGroup;
  theme: ThemeDefinition;
  onChange: (field: ThemeFieldConfig, rawValue: string) => void;
}) {
  const { t } = useI18n();

  return (
    <section className="theme-settings__group">
      <h3 className="theme-settings__group-title">{t(group.titleKey)}</h3>
      <div className="theme-settings__grid">
        {group.fields.map((field) => (
          <ThemeField
            key={field.path}
            disabled={disabled}
            field={field}
            value={getThemePathValue(theme, field.path)}
            onChange={onChange}
          />
        ))}
      </div>
    </section>
  );
}

function ThemeField({
  disabled,
  field,
  value,
  onChange,
}: {
  disabled: boolean;
  field: ThemeFieldConfig;
  value: unknown;
  onChange: (field: ThemeFieldConfig, rawValue: string) => void;
}) {
  const { t } = useI18n();
  const stringValue = formatFieldValue(value);
  const inputDisabled = disabled || field.readOnly === true;
  const label = t(field.labelKey);
  const options = translateThemeFieldOptions(field.options, t);

  return (
    <label className="theme-settings__control">
      <span className="theme-settings__label">{label}</span>
      <span className="theme-settings__control-row">
        {renderFieldInput({
          disabled: inputDisabled,
          field,
          label,
          options,
          value: stringValue,
          onChange,
        })}
      </span>
    </label>
  );
}

function renderFieldInput({
  disabled,
  field,
  label,
  options,
  value,
  onChange,
}: {
  disabled: boolean;
  field: ThemeFieldConfig;
  label: string;
  options?: Array<OptionSelectItem<string>>;
  value: string;
  onChange: (field: ThemeFieldConfig, rawValue: string) => void;
}) {
  if (field.kind === "boolean") {
    const checked = value === "true";
    return (
      <button
        aria-checked={checked}
        aria-label={label}
        className={
          checked
            ? "theme-settings__switch theme-settings__switch--on"
            : "theme-settings__switch"
        }
        disabled={disabled}
        role="switch"
        type="button"
        onClick={() => onChange(field, checked ? "false" : "true")}
      >
        <span aria-hidden="true" />
      </button>
    );
  }

  if (field.kind === "select") {
    return (
      <OptionSelect
        ariaLabel={label}
        className="theme-settings__option-select"
        disabled={disabled}
        value={value}
        floating
        options={options ?? []}
        showSelectedOption
        onChange={(nextValue) => onChange(field, nextValue)}
      />
    );
  }

  if (field.kind === "number") {
    return (
      <input
        className="theme-settings__input"
        disabled={disabled}
        max={field.max}
        min={field.min}
        readOnly={field.readOnly}
        step={field.step ?? 1}
        type="number"
        value={value}
        onChange={(event) => onChange(field, event.target.value)}
      />
    );
  }

  if (field.kind === "color") {
    return (
      <ThemeColorInput
        disabled={disabled}
        field={field}
        label={label}
        value={value}
        onChange={onChange}
      />
    );
  }

  return (
    <input
      className="theme-settings__input"
      disabled={disabled}
      readOnly={field.readOnly}
      type="text"
      value={value}
      onChange={(event) => onChange(field, event.target.value)}
    />
  );
}

function ThemeColorInput({
  disabled,
  field,
  label,
  value,
  onChange,
}: {
  disabled: boolean;
  field: ThemeFieldConfig;
  label: string;
  value: string;
  onChange: (field: ThemeFieldConfig, rawValue: string) => void;
}) {
  const { t } = useI18n();
  const colorPickerValue = toColorPickerValue(value);

  return (
    <span className="theme-settings__color-control">
      <input
        aria-label={`${label}${t("themeSettings.colorPickerSuffix")}`}
        className="theme-settings__color"
        disabled={disabled || colorPickerValue === null}
        type="color"
        value={colorPickerValue ?? "#000000"}
        onChange={(event) =>
          onChange(field, applyColorPickerValue(value, event.target.value))
        }
      />
      <input
        className="theme-settings__input"
        disabled={disabled}
        readOnly={field.readOnly}
        type="text"
        value={value}
        onChange={(event) => onChange(field, event.target.value)}
      />
    </span>
  );
}

function formatFieldValue(value: unknown): string {
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "true" : "false";
  if (value === null || value === undefined) return "";
  return String(value);
}

function parseFieldInputValue(
  field: ThemeFieldConfig,
  rawValue: string,
): string | number | boolean {
  if (field.kind === "boolean") return rawValue === "true";
  if (field.kind !== "number") return rawValue;
  if (!rawValue.trim()) return 0;
  const nextValue = Number(rawValue);
  return Number.isFinite(nextValue) ? nextValue : 0;
}

function translateThemeFieldOptions(
  options: readonly { labelKey: TranslationKey; value: string }[] | undefined,
  t: (key: TranslationKey) => string,
): Array<OptionSelectItem<string>> | undefined {
  return options?.map((option) => ({
    label: t(option.labelKey),
    value: option.value,
  }));
}

function getThemePathValue(theme: ThemeDefinition, path: string): unknown {
  return path.split(".").reduce<unknown>((current, key) => {
    if (!current || typeof current !== "object" || Array.isArray(current)) {
      return undefined;
    }
    return (current as Record<string, unknown>)[key];
  }, theme);
}

function setThemePathValue(
  theme: ThemeDefinition,
  path: string,
  value: string | number | boolean,
): ThemeDefinition {
  const parts = path.split(".");
  const root = { ...(theme as unknown as Record<string, unknown>) };
  let cursor = root;

  for (const key of parts.slice(0, -1)) {
    const current = cursor[key];
    const next =
      current && typeof current === "object" && !Array.isArray(current)
        ? { ...(current as Record<string, unknown>) }
        : {};
    cursor[key] = next;
    cursor = next;
  }

  cursor[parts[parts.length - 1]] = value;
  return root as unknown as ThemeDefinition;
}

function fingerprintTheme(theme: ThemeDefinition): string {
  return JSON.stringify(theme);
}

function mergeThemeSummary(
  themes: ThemeSummary[],
  theme: ThemeDefinition,
): ThemeSummary[] {
  const nextSummary: ThemeSummary = {
    id: theme.id,
    mode: theme.mode,
    name: theme.name,
  };
  if (themes.some((item) => item.id === theme.id)) {
    return themes.map((item) => (item.id === theme.id ? nextSummary : item));
  }
  return [...themes, nextSummary];
}
