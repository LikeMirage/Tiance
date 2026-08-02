import { useEffect } from "react";

import { useI18n } from "../../../shared/i18n";
import type { TokenEstimationSettings } from "../../../services/llm/tokenEstimationSettings";
import { useTokenEstimationSettings } from "../model/useTokenEstimationSettings";

import "./token-estimation-settings.css";

type TokenEstimationSettingsPanelProps = {
  onReady?: () => void;
};

type NumericSettingFieldProps = {
  label: string;
  max: number;
  min: number;
  onChange: (value: number) => void;
  step: number;
  unit: string;
  value: number;
};

export function TokenEstimationSettingsPanel({
  onReady,
}: TokenEstimationSettingsPanelProps) {
  const { t } = useI18n();
  const settings = useTokenEstimationSettings();

  useEffect(() => {
    onReady?.();
  }, [onReady]);

  return (
    <div className="token-estimation-settings">
      <section
        className="token-estimation-settings__section"
        aria-labelledby="token-estimation-settings-title"
      >
        <header className="token-estimation-settings__head">
          <h2
            id="token-estimation-settings-title"
            className="token-estimation-settings__title"
          >
            {t("tokenEstimationSettings.title")}
          </h2>
          <div className="token-estimation-settings__actions">
            <button
              className="token-estimation-settings__secondary"
              type="button"
              disabled={settings.isLoading || !settings.draft}
              onClick={settings.reset}
            >
              {t("tokenEstimationSettings.reset")}
            </button>
          </div>
        </header>

        <div className="token-estimation-settings__notice">
          <strong>{t("tokenEstimationSettings.activationTitle")}</strong>
          <p>{t("tokenEstimationSettings.activationDescription")}</p>
          <p>{t("tokenEstimationSettings.historyDescription")}</p>
        </div>

        {settings.error ? (
          <div className="token-estimation-settings__error" role="alert">
            {settings.error}
          </div>
        ) : null}

        {settings.isLoading || !settings.draft ? (
          <div className="token-estimation-settings__loading" role="status">
            {t("tokenEstimationSettings.loading")}
          </div>
        ) : (
          <>
            <div className="token-estimation-settings__algorithm">
              <h3>{t("tokenEstimationSettings.algorithmTitle")}</h3>
              <p>{t("tokenEstimationSettings.algorithmDescription")}</p>
            </div>
            <div className="token-estimation-settings__grid">
              <NumericSettingField
                label={t("tokenEstimationSettings.fields.asciiCharsPerToken")}
                min={0.1}
                max={16}
                step={0.1}
                unit={t("tokenEstimationSettings.units.charsPerToken")}
                value={settings.draft.ascii_chars_per_token}
                onChange={(value) => settings.updateSetting("ascii_chars_per_token", value)}
              />
              <NumericSettingField
                label={t("tokenEstimationSettings.fields.otherCharsPerToken")}
                min={0.1}
                max={16}
                step={0.1}
                unit={t("tokenEstimationSettings.units.charsPerToken")}
                value={settings.draft.other_chars_per_token}
                onChange={(value) => settings.updateSetting("other_chars_per_token", value)}
              />
              <NumericSettingField
                label={t("tokenEstimationSettings.fields.messageOverheadTokens")}
                min={0}
                max={128}
                step={1}
                unit={t("tokenEstimationSettings.units.tokensPerMessage")}
                value={settings.draft.message_overhead_tokens}
                onChange={(value) => settings.updateSetting("message_overhead_tokens", value)}
              />
              <NumericSettingField
                label={t("tokenEstimationSettings.fields.imagePlaceholderTokens")}
                min={0}
                max={32768}
                step={1}
                unit={t("tokenEstimationSettings.units.tokensPerImage")}
                value={settings.draft.image_placeholder_tokens}
                onChange={(value) => settings.updateSetting("image_placeholder_tokens", value)}
              />
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function NumericSettingField({
  label,
  max,
  min,
  onChange,
  step,
  unit,
  value,
}: NumericSettingFieldProps) {
  return (
    <label className="token-estimation-settings__field">
      <span className="token-estimation-settings__label">{label}</span>
      <span className="token-estimation-settings__number-shell">
        <input
          className="token-estimation-settings__number"
          type="number"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(event) => {
            const next = event.currentTarget.valueAsNumber;
            if (Number.isFinite(next)) {
              onChange(next);
            }
          }}
        />
        <span className="token-estimation-settings__unit">{unit}</span>
      </span>
    </label>
  );
}
