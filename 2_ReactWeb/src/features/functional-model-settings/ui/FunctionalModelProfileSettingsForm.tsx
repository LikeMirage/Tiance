import { useState } from "react";

import type {
  DsLlmOutputFormat,
  DsLlmReasoningMode,
} from "../../../entities/llm-runtime/model/generationParams";
import type { DsLlmSamplingParameter } from "../../../entities/llm-runtime/model/runtimeCapabilities";
import { useI18n, type TranslationKey } from "../../../shared/i18n";
import {
  getLlmModelPickerOptionKey,
  toLlmModelPickerOption,
  toUnavailableLlmModelPickerOption,
} from "../../llm-model-picker/model/llmModelPickerOption";
import { LlmModelPicker } from "../../llm-model-picker/ui/LlmModelPicker";
import { OptionSelect, type OptionSelectItem } from "../../../shared/ui/option-select/OptionSelect";
import type {
  FunctionalModelProfileKey,
  FunctionalModelProfileSettingsMap,
} from "../model/functionalModelSettings";
import {
  getFunctionalModelKey,
  useFunctionalModelSettings,
} from "../model/useFunctionalModelSettings";
import { isRuntimeCapabilitiesUnavailable } from "../model/unavailableRuntimeCapabilities";

type PromptFunctionalModelProfileKey = Exclude<FunctionalModelProfileKey, "defaultConversation">;

const SESSION_MODEL_OPTION_PROVIDER_ID = "__session_model_source__";

type PromptTabConfig<K extends PromptFunctionalModelProfileKey> = {
  key: Extract<keyof FunctionalModelProfileSettingsMap[K], string>;
  label: string;
  syncPromptKey?: Extract<keyof FunctionalModelProfileSettingsMap[K], string>;
};

type AdditionalNumberFieldConfig<K extends PromptFunctionalModelProfileKey> = {
  defaultValue: number;
  description?: string;
  key: Extract<keyof FunctionalModelProfileSettingsMap[K], string>;
  label: string;
  max?: number;
  min: number;
  step?: number;
};

type AdditionalBooleanFieldConfig<K extends PromptFunctionalModelProfileKey> = {
  description?: string;
  key: Extract<keyof FunctionalModelProfileSettingsMap[K], string>;
  label: string;
};

type FunctionalModelProfileSettingsFormProps<K extends PromptFunctionalModelProfileKey> = {
  additionalBooleanFields?: Array<AdditionalBooleanFieldConfig<K>>;
  additionalNumberFields?: Array<AdditionalNumberFieldConfig<K>>;
  emptyModelsHint?: string;
  modelAriaLabel: string;
  modelPlaceholder?: string;
  promptTabs?: Array<PromptTabConfig<K>>;
  hideGenerationControlsForSessionModel?: boolean;
  showOutputFormatControl?: boolean;
  sessionModelOption?: {
    description: string;
    groupLabel: string;
    label: string;
    notes: readonly string[];
    reasoningPlaceholder: string;
  };
  title: string;
  titleId: string;
  profileKey: K;
};

export function FunctionalModelProfileSettingsForm<K extends PromptFunctionalModelProfileKey>({
  additionalBooleanFields,
  additionalNumberFields,
  emptyModelsHint,
  modelAriaLabel,
  modelPlaceholder,
  profileKey,
  promptTabs,
  hideGenerationControlsForSessionModel = false,
  showOutputFormatControl = true,
  sessionModelOption,
  title,
  titleId,
}: FunctionalModelProfileSettingsFormProps<K>) {
  const { t } = useI18n();
  const modelSettings = useFunctionalModelSettings(profileKey);
  const { runtimeCapabilities, settings } = modelSettings;
  const isSettingsFormDisabled = modelSettings.isLoadingSettings;
  const usesSessionModel = Boolean(
    sessionModelOption
    && "modelSource" in settings
    && settings.modelSource === "session",
  );
  const showGenerationControls = !(usesSessionModel && hideGenerationControlsForSessionModel);
  const isRuntimeCapabilitiesUnknown = isRuntimeCapabilitiesUnavailable(runtimeCapabilities);
  const [activePromptTabKey, setActivePromptTabKey] = useState<string>(() =>
    promptTabs?.[0]?.key ?? "prompt",
  );
  const reasoningMode = settings.generation.reasoning?.mode ?? "default";
  const supportedSamplingParameters = new Set(runtimeCapabilities.sampling.parameters);
  const isSamplingDisabled =
    runtimeCapabilities.sampling.disabledWhenReasoning &&
    reasoningMode !== "default" &&
    reasoningMode !== "off";
  const isSamplingParameterDisabled = (parameter: DsLlmSamplingParameter) =>
    !usesSessionModel && (
    isRuntimeCapabilitiesUnknown
    || !runtimeCapabilities.sampling.supported
    || !supportedSamplingParameters.has(parameter)
    || isSamplingDisabled);
  const activePromptTab = promptTabs?.find((tab) => tab.key === activePromptTabKey)
    ?? promptTabs?.[0]
    ?? null;
  const activePromptKey = activePromptTab?.key ?? "prompt";
  const activePrompt = getPromptValue(settings, activePromptKey);
  const resolvedEmptyModelsHint =
    emptyModelsHint ?? t("functionalModelSettings.common.noTextModels");
  const resolvedModelPlaceholder =
    modelPlaceholder ?? t("functionalModelSettings.common.recommendedDeepSeek");
  const selectedModelStillAvailable = modelSettings.eligibleTextModels.some((model) =>
    getFunctionalModelKey(model) === settings.modelKey,
  );
  const unavailableSelectedModel =
    !usesSessionModel && settings.modelKey && !selectedModelStillAvailable
      ? toUnavailableLlmModelPickerOption(settings.modelKey)
      : null;
  const sessionModelPickerOption = sessionModelOption
    ? {
        annotation: {
          notes: sessionModelOption.notes,
          summary: sessionModelOption.description,
        },
        modelId: sessionModelOption.label,
        modelLabel: sessionModelOption.label,
        providerId: SESSION_MODEL_OPTION_PROVIDER_ID,
        providerLabel: sessionModelOption.groupLabel,
      }
    : null;
  const sessionModelPickerValue = sessionModelPickerOption
    ? getLlmModelPickerOptionKey(sessionModelPickerOption)
    : "";
  const modelOptions = [
    ...(sessionModelPickerOption ? [sessionModelPickerOption] : []),
    ...(unavailableSelectedModel ? [unavailableSelectedModel] : []),
    ...modelSettings.eligibleTextModels.map(toLlmModelPickerOption),
  ];

  const reasoningOptions: Array<OptionSelectItem<DsLlmReasoningMode>> =
    (!isRuntimeCapabilitiesUnknown && runtimeCapabilities.reasoning.modes.length > 0
      ? runtimeCapabilities.reasoning.modes
      : (["default"] as const)
    ).map((mode) => ({
      label: getReasoningModeLabel(t, mode),
      value: mode,
    }));

  const outputFormatOptions: Array<OptionSelectItem<DsLlmOutputFormat>> =
    (!isRuntimeCapabilitiesUnknown && runtimeCapabilities.outputFormats.length > 0
      ? runtimeCapabilities.outputFormats
      : (["text"] as const)
    ).map((format) => ({
      label: getOutputFormatLabel(t, format),
      value: format,
    }));

  return (
    <section className="functional-model-settings__section" aria-labelledby={titleId}>
      <header className="functional-model-settings__head">
        <div>
          <h2 id={titleId} className="functional-model-settings__title">
            {title}
          </h2>
        </div>
        <button
          className="functional-model-settings__secondary"
          type="button"
          disabled={modelSettings.isLoadingSettings}
          onClick={() => {
            void modelSettings.resetSettings();
          }}
        >
          {t("common.actions.reset")}
        </button>
      </header>

      <div className="functional-model-settings__form">
        <label className="functional-model-settings__field">
          <span className="functional-model-settings__label">{t("functionalModelSettings.common.model")}</span>
          <LlmModelPicker
            allowClear={!usesSessionModel && Boolean(settings.modelKey)}
            ariaLabel={modelAriaLabel}
            className="functional-model-settings__model-picker"
            disabled={
              isSettingsFormDisabled ||
              modelSettings.isLoadingModels
              && modelOptions.length === 0
            }
            error={null}
            loading={modelSettings.isLoadingModels}
            options={modelOptions}
            placeholder={
              modelSettings.isLoadingModels
                ? t("functionalModelSettings.common.loadingModels")
                : resolvedModelPlaceholder
            }
            value={usesSessionModel ? sessionModelPickerValue : settings.modelKey}
            onChange={(value, option) => {
              if (option?.providerId === SESSION_MODEL_OPTION_PROVIDER_ID) {
                updateModelSource(modelSettings.updateProfileSetting, "session");
                return;
              }
              modelSettings.updateProfileSetting("modelKey", value);
              if (sessionModelOption) {
                updateModelSource(modelSettings.updateProfileSetting, "dedicated");
              }
            }}
            onOpen={() => {
              void modelSettings.reloadModels({ silent: true });
            }}
          />
        </label>

        {modelSettings.error ? (
          <div className="functional-model-settings__error" role="status">
            {modelSettings.error}
          </div>
        ) : !modelSettings.isLoadingModels && modelSettings.eligibleTextModels.length === 0 ? (
          <div className="functional-model-settings__hint" role="status">
            {resolvedEmptyModelsHint}
          </div>
        ) : null}

        {showGenerationControls ? (
        <div className="functional-model-settings__grid">
          <label className="functional-model-settings__field">
            <span className="functional-model-settings__label">{t("functionalModelSettings.common.reasoningDepth")}</span>
            {usesSessionModel && sessionModelOption ? (
              <div className="functional-model-settings__readonly-value">
                {sessionModelOption.reasoningPlaceholder}
              </div>
            ) : (
              <OptionSelect
                ariaLabel={t("functionalModelSettings.common.reasoningDepth")}
                className="functional-model-settings__option-select"
                disabled={isSettingsFormDisabled || isRuntimeCapabilitiesUnknown || !runtimeCapabilities.reasoning.supported}
                floating
                options={reasoningOptions}
                value={reasoningMode}
                onChange={(value) => {
                  modelSettings.updateGenerationParam("reasoning", { mode: value });
                }}
              />
            )}
          </label>
        </div>
        ) : null}

        {showGenerationControls ? (
        <div className="functional-model-settings__grid">
          <NumberField
            disabled={isSettingsFormDisabled || isSamplingParameterDisabled("temperature")}
            label={t("functionalModelSettings.common.temperature")}
            min={0}
            step={0.1}
            value={settings.generation.temperature ?? 0.2}
            onChange={(value) => modelSettings.updateGenerationParam("temperature", value)}
          />
          <NumberField
            disabled={isSettingsFormDisabled || isSamplingParameterDisabled("topP")}
            label="top_p"
            min={0}
            step={0.05}
            value={settings.generation.topP ?? 1}
            onChange={(value) => modelSettings.updateGenerationParam("topP", value)}
          />
        </div>
        ) : null}

        {showGenerationControls ? (
        <div className="functional-model-settings__grid">
          <NumberField
            disabled={isSettingsFormDisabled || (!usesSessionModel && !runtimeCapabilities.maxOutputTokens.supported)}
            label={t("functionalModelSettings.common.maxOutputTokens")}
            min={usesSessionModel ? 1 : runtimeCapabilities.maxOutputTokens.min}
            value={settings.generation.maxOutputTokens ?? 100}
            onChange={(value) => modelSettings.updateGenerationParam("maxOutputTokens", value)}
          />

          {showOutputFormatControl ? (
            <label className="functional-model-settings__field">
              <span className="functional-model-settings__label">{t("functionalModelSettings.common.jsonOutput")}</span>
              <OptionSelect
                ariaLabel={t("functionalModelSettings.common.jsonOutput")}
                className="functional-model-settings__option-select"
                disabled={isSettingsFormDisabled || isRuntimeCapabilitiesUnknown || outputFormatOptions.length === 0}
                floating
                options={outputFormatOptions}
                value={settings.output.format}
                onChange={modelSettings.updateOutputFormat}
              />
            </label>
          ) : null}
        </div>
        ) : null}

        {additionalBooleanFields && additionalBooleanFields.length > 0 ? (
          <div className="functional-model-settings__switch-grid">
            {additionalBooleanFields.map((field) => (
              <label key={field.key} className="functional-model-settings__switch-field">
                <span>
                  <span className="functional-model-settings__label">{field.label}</span>
                  {field.description ? (
                    <span className="functional-model-settings__field-description">
                      {field.description}
                    </span>
                  ) : null}
                </span>
                <input
                  className="functional-model-settings__switch"
                  checked={getBooleanSettingValue(settings, field.key)}
                  disabled={isSettingsFormDisabled}
                  type="checkbox"
                  onChange={(event) => {
                    updateBooleanSetting(
                      modelSettings.updateProfileSetting,
                      field.key,
                      event.target.checked,
                    );
                  }}
                />
              </label>
            ))}
          </div>
        ) : null}

        {additionalNumberFields && additionalNumberFields.length > 0 ? (
          <div className="functional-model-settings__grid">
            {additionalNumberFields.map((field) => (
              <NumberField
                key={field.key}
                description={field.description}
                disabled={isSettingsFormDisabled}
                label={field.label}
                max={field.max}
                min={field.min}
                step={field.step}
                value={getNumberSettingValue(settings, field.key, field.defaultValue)}
                onChange={(value) => {
                  updateNumberSetting(
                    modelSettings.updateProfileSetting,
                    field.key,
                    value,
                  );
                }}
              />
            ))}
          </div>
        ) : null}

        <label className="functional-model-settings__field">
          <span className="functional-model-settings__label">{t("functionalModelSettings.common.prompt")}</span>
          {promptTabs && promptTabs.length > 0 ? (
            <div
              className="functional-model-settings__prompt-tabs"
              role="tablist"
              aria-label={t("functionalModelSettings.common.promptType", { title })}
            >
              {promptTabs.map((tab) => (
                <button
                  key={tab.key}
                  className={
                    tab.key === activePromptKey
                      ? "functional-model-settings__prompt-tab functional-model-settings__prompt-tab--active"
                      : "functional-model-settings__prompt-tab"
                  }
                  role="tab"
                  type="button"
                  aria-selected={tab.key === activePromptKey}
                  disabled={isSettingsFormDisabled}
                  onClick={() => setActivePromptTabKey(tab.key)}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          ) : null}
          <textarea
            className="functional-model-settings__textarea"
            disabled={isSettingsFormDisabled}
            value={activePrompt}
            onChange={(event) => {
              updatePromptSetting(
                modelSettings.updateProfileSetting,
                activePromptKey,
                event.target.value,
                activePromptTab?.syncPromptKey,
              );
            }}
          />
        </label>

        <div className="functional-model-settings__actions">
          <button
            className="functional-model-settings__secondary"
            type="button"
            disabled={modelSettings.isLoadingSettings}
            onClick={() => {
              if (!activePromptTab) {
                void modelSettings.resetPrompt();
                return;
              }
              void modelSettings.resetPrompt({
                key: activePromptTab.key,
                syncPromptKey: activePromptTab.syncPromptKey,
              });
            }}
          >
            {t("functionalModelSettings.common.resetPrompt")}
          </button>
        </div>
      </div>
    </section>
  );
}

function getReasoningModeLabel(
  t: (key: TranslationKey) => string,
  mode: DsLlmReasoningMode,
) {
  switch (mode) {
    case "default":
      return t("aiPanel.reasoningModes.default");
    case "auto":
      return t("aiPanel.reasoningModes.auto");
    case "enabled":
      return t("aiPanel.reasoningModes.enabled");
    case "off":
      return t("aiPanel.reasoningModes.off");
    case "low":
      return t("aiPanel.reasoningModes.low");
    case "medium":
      return t("aiPanel.reasoningModes.medium");
    case "high":
      return t("aiPanel.reasoningModes.high");
    case "max":
      return t("aiPanel.reasoningModes.max");
  }
}

function getOutputFormatLabel(
  t: (key: TranslationKey) => string,
  format: DsLlmOutputFormat,
) {
  switch (format) {
    case "json_object":
      return t("functionalModelSettings.common.outputFormats.jsonObject");
    case "text":
      return t("functionalModelSettings.common.outputFormats.text");
  }
}

type NumberFieldProps = {
  description?: string;
  disabled?: boolean;
  label: string;
  max?: number | null;
  min: number;
  onChange: (value: number) => void;
  step?: number;
  value: number;
};

function NumberField({
  description,
  disabled = false,
  label,
  max,
  min,
  onChange,
  step,
  value,
}: NumberFieldProps) {
  return (
    <label className="functional-model-settings__field">
      <span className="functional-model-settings__label">{label}</span>
      {description ? (
        <span className="functional-model-settings__field-description">{description}</span>
      ) : null}
      <input
        className="functional-model-settings__number"
        type="number"
        disabled={disabled}
        min={min}
        max={max ?? undefined}
        step={step}
        value={value}
        onChange={(event) => {
          onChange(clampNumberInput(event.target.value, min, max));
        }}
      />
    </label>
  );
}

function getNumberSettingValue<K extends PromptFunctionalModelProfileKey>(
  settings: FunctionalModelProfileSettingsMap[K],
  key: Extract<keyof FunctionalModelProfileSettingsMap[K], string>,
  defaultValue: number,
) {
  const value = settings[key];
  return typeof value === "number" && Number.isFinite(value) ? value : defaultValue;
}

function getBooleanSettingValue<K extends PromptFunctionalModelProfileKey>(
  settings: FunctionalModelProfileSettingsMap[K],
  key: Extract<keyof FunctionalModelProfileSettingsMap[K], string>,
) {
  return settings[key] === true;
}

function updateBooleanSetting<K extends PromptFunctionalModelProfileKey>(
  updateProfileSetting: <P extends keyof FunctionalModelProfileSettingsMap[K]>(
    key: P,
    value: FunctionalModelProfileSettingsMap[K][P],
  ) => void,
  key: Extract<keyof FunctionalModelProfileSettingsMap[K], string>,
  value: boolean,
) {
  updateProfileSetting(
    key,
    value as FunctionalModelProfileSettingsMap[K][typeof key],
  );
}

function updateNumberSetting<K extends PromptFunctionalModelProfileKey>(
  updateProfileSetting: <P extends keyof FunctionalModelProfileSettingsMap[K]>(
    key: P,
    value: FunctionalModelProfileSettingsMap[K][P],
  ) => void,
  key: Extract<keyof FunctionalModelProfileSettingsMap[K], string>,
  value: number,
) {
  updateProfileSetting(
    key,
    value as FunctionalModelProfileSettingsMap[K][typeof key],
  );
}

function getPromptValue<K extends PromptFunctionalModelProfileKey>(
  settings: FunctionalModelProfileSettingsMap[K],
  key: string,
) {
  const value = settings[key as keyof FunctionalModelProfileSettingsMap[K]];
  return typeof value === "string" ? value : "";
}

function updatePromptSetting<K extends PromptFunctionalModelProfileKey>(
  updateProfileSetting: <P extends keyof FunctionalModelProfileSettingsMap[K]>(
    key: P,
    value: FunctionalModelProfileSettingsMap[K][P],
  ) => void,
  key: string,
  value: string,
  syncPromptKey?: string,
) {
  updateProfileSetting(
    key as keyof FunctionalModelProfileSettingsMap[K],
    value as FunctionalModelProfileSettingsMap[K][keyof FunctionalModelProfileSettingsMap[K]],
  );
  if (syncPromptKey) {
    updateProfileSetting(
      syncPromptKey as keyof FunctionalModelProfileSettingsMap[K],
      value as FunctionalModelProfileSettingsMap[K][keyof FunctionalModelProfileSettingsMap[K]],
    );
  }
}

function updateModelSource<K extends PromptFunctionalModelProfileKey>(
  updateProfileSetting: <P extends keyof FunctionalModelProfileSettingsMap[K]>(
    key: P,
    value: FunctionalModelProfileSettingsMap[K][P],
  ) => void,
  value: "session" | "dedicated",
) {
  updateProfileSetting(
    "modelSource" as keyof FunctionalModelProfileSettingsMap[K],
    value as FunctionalModelProfileSettingsMap[K][keyof FunctionalModelProfileSettingsMap[K]],
  );
}

function clampNumberInput(value: string, min: number, max?: number | null) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return min;
  }

  const minBoundedValue = Math.max(min, parsed);
  return max === null || max === undefined
    ? minBoundedValue
    : Math.min(max, minBoundedValue);
}
