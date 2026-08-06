import { useState, type RefObject } from "react";

import type { ProviderProtocolFamily } from "../../../entities/llm-provider/model/providerCatalog";
import { useI18n } from "../../../shared/i18n";
import { OptionSelect } from "../../../shared/ui/option-select/OptionSelect";
import type { UseProviderConfigStateResult } from "../model/useProviderConfigState";
import {
  completeProviderGenerationUrl,
  completeProviderModelDiscoveryUrl,
} from "../model/completeProviderGenerationUrl";
import {
  PROVIDER_AUTH_SCHEME_OPTIONS,
  PROVIDER_MODEL_DISCOVERY_STRATEGY_OPTIONS,
  PROVIDER_PROTOCOL_FAMILY_OPTIONS,
} from "./providerProtocolOptions";

type ProviderConfigDraft = NonNullable<UseProviderConfigStateResult["selectedDraft"]>;

type ProviderConfigSectionProps = {
  providerConfigState: UseProviderConfigStateResult;
  providerDisplayName: string;
  selectedProviderDraft: ProviderConfigDraft;
};

type ProviderApiKeySectionProps = ProviderConfigSectionProps & {
  apiKeyInputRefs: RefObject<Map<string, HTMLInputElement>>;
};

type ProviderApiBaseUrlSectionProps = ProviderConfigSectionProps & {
  isUpdatingProviderProtocol: boolean;
  onUpdateProviderProtocol: (protocolFamily: ProviderProtocolFamily) => void;
  protocolFamily: ProviderProtocolFamily;
};

type ApiAddressConfigMode = "generation" | "models";

const PROMPT_CACHE_RETENTION_UNIT_OPTIONS = [
  { label: "", value: "minutes" },
  { label: "", value: "hours" },
] as const;

export function ProviderApiKeySection({
  apiKeyInputRefs,
  providerConfigState,
  providerDisplayName,
  selectedProviderDraft,
}: ProviderApiKeySectionProps) {
  const { t } = useI18n();

  return (
    <div className="provider-canvas__canvas-group">
      <header className="provider-canvas__canvas-section-head provider-canvas__api-key-section-head">
        <div>
          <h3 className="provider-canvas__canvas-section-title">
            {t("providerCanvas.apiKey.title")}
          </h3>
        </div>
        <button
          className="provider-canvas__canvas-plus"
          type="button"
          onClick={providerConfigState.addSelectedApiKey}
          aria-label={t("providerCanvas.apiKey.add")}
        >
          +
        </button>
      </header>

      <div className="provider-canvas__api-key-list">
        {selectedProviderDraft.apiKeys.map((apiKey, index) => (
          <div key={apiKey.id} className="provider-canvas__api-key-row">
            <div className="provider-canvas__canvas-input-shell provider-canvas__canvas-input-shell--with-poll">
              <input
                ref={(node) => {
                  if (node) {
                    apiKeyInputRefs.current.set(apiKey.id, node);
                    return;
                  }

                  apiKeyInputRefs.current.delete(apiKey.id);
                }}
                className="provider-canvas__canvas-input provider-canvas__canvas-input--with-button"
                type="password"
                autoComplete="off"
                aria-label={`${providerDisplayName} API KEY ${index + 1}`}
                value={apiKey.value}
                placeholder={
                  apiKey.apiKeyHint
                    ? t("providerCanvas.apiKey.savedPlaceholder", {
                      hint: apiKey.apiKeyHint,
                    })
                    : t("providerCanvas.apiKey.emptyPlaceholder", {
                      provider: providerDisplayName,
                    })
                }
                onBlur={() => {
                  providerConfigState.removeSelectedApiKeyIfEmpty(apiKey.id);
                }}
                onChange={(event) =>
                  providerConfigState.updateSelectedApiKey(
                    apiKey.id,
                    event.target.value,
                  )
                }
              />
              <button
                className="provider-canvas__canvas-input-action provider-canvas__canvas-input-action--clear"
                type="button"
                aria-label={t("providerCanvas.apiKey.clearAria", {
                  index: index + 1,
                  provider: providerDisplayName,
                })}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  providerConfigState.clearSelectedApiKey(apiKey.id);
                  window.requestAnimationFrame(() => {
                    apiKeyInputRefs.current.get(apiKey.id)?.focus();
                  });
                }}
              >
                {t("common.actions.clear")}
              </button>
              <label
                className="provider-canvas__api-key-poll-control"
                title={t("providerCanvas.apiKey.pollTitle")}
              >
                <span className="provider-canvas__api-key-poll-label">
                  {t("providerCanvas.apiKey.pollLabel")}
                </span>
                <input
                  className="provider-canvas__api-key-poll-input"
                  type="number"
                  inputMode="numeric"
                  min="0"
                  aria-label={t("providerCanvas.apiKey.pollAria", {
                    index: index + 1,
                    provider: providerDisplayName,
                  })}
                  value={apiKey.pollWeight}
                  onBlur={() => {
                    void providerConfigState.saveSelectedProviderConfig();
                  }}
                  onChange={(event) =>
                    providerConfigState.updateSelectedApiKeyPollWeight(
                      apiKey.id,
                      event.target.value,
                    )
                  }
                />
              </label>
              <div
                className="provider-canvas__api-key-rpm"
                title={t("providerCanvas.apiKey.rpmTitle")}
                aria-label={`${providerDisplayName} API KEY ${index + 1} RPM`}
              >
                <span className="provider-canvas__api-key-rpm-label">RPM</span>
                <span className="provider-canvas__api-key-rpm-value">
                  {apiKey.rpm}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ProviderApiBaseUrlSection({
  isUpdatingProviderProtocol,
  onUpdateProviderProtocol,
  protocolFamily,
  providerConfigState,
  providerDisplayName,
  selectedProviderDraft,
}: ProviderApiBaseUrlSectionProps) {
  const { t } = useI18n();
  const completedApiBaseUrl = completeProviderGenerationUrl(
    selectedProviderDraft.apiBaseUrl,
    protocolFamily,
    selectedProviderDraft.presetApiBaseUrl,
  );
  const canCompleteApiBaseUrl =
    completedApiBaseUrl.length > 0
    && completedApiBaseUrl !== selectedProviderDraft.apiBaseUrl.trim();
  const completedModelDiscoveryUrl = completeProviderModelDiscoveryUrl(
    completedApiBaseUrl,
    protocolFamily,
    selectedProviderDraft.presetModelDiscoveryUrl,
  );
  const shouldCompleteModelDiscoveryUrl =
    selectedProviderDraft.modelDiscoveryUrl.trim().length === 0
    || selectedProviderDraft.modelDiscoveryUrl === selectedProviderDraft.presetModelDiscoveryUrl;
  const [activeConfigMode, setActiveConfigMode] =
    useState<ApiAddressConfigMode>("generation");
  const protocolFamilyOptions = PROVIDER_PROTOCOL_FAMILY_OPTIONS.map((option) => ({
    ...option,
    label: getProviderProtocolLabel(option.value, t),
  }));

  return (
    <div className="provider-canvas__canvas-group">
      <header className="provider-canvas__canvas-section-head provider-canvas__api-address-section-head">
        <div className="provider-canvas__api-address-heading">
          <h3 className="provider-canvas__canvas-section-title">
            {t("providerCanvas.apiAddress.title")}
          </h3>
          <div
            className="provider-canvas__api-address-tabs"
            role="tablist"
            aria-label={t("providerCanvas.apiAddress.tabsAria")}
          >
            <button
              id="provider-api-address-tab-generation"
              className={
                activeConfigMode === "generation"
                  ? "provider-canvas__api-address-tab provider-canvas__api-address-tab--active"
                  : "provider-canvas__api-address-tab"
              }
              type="button"
              role="tab"
              aria-controls="provider-api-address-panel-generation"
              aria-selected={activeConfigMode === "generation"}
              onClick={() => setActiveConfigMode("generation")}
            >
              {t("providerCanvas.apiAddress.generationTab")}
            </button>
            <button
              id="provider-api-address-tab-models"
              className={
                activeConfigMode === "models"
                  ? "provider-canvas__api-address-tab provider-canvas__api-address-tab--active"
                  : "provider-canvas__api-address-tab"
              }
              type="button"
              role="tab"
              aria-controls="provider-api-address-panel-models"
              aria-selected={activeConfigMode === "models"}
              onClick={() => setActiveConfigMode("models")}
            >
              {t("providerCanvas.apiAddress.modelsTab")}
            </button>
          </div>
        </div>
      </header>

      {activeConfigMode === "generation" ? (
        <div
          id="provider-api-address-panel-generation"
          className="provider-canvas__canvas-field"
          role="tabpanel"
          aria-labelledby="provider-api-address-tab-generation"
        >
          <label className="provider-canvas__canvas-field-label">
            {t("providerCanvas.apiAddress.generationProtocol")}
          </label>
          <OptionSelect
            ariaLabel={t("providerCanvas.selectProviderProtocol")}
            className="provider-canvas__provider-protocol-select"
            disabled={isUpdatingProviderProtocol}
            options={protocolFamilyOptions}
            value={protocolFamily}
            variant="integrated-overlay"
            onChange={onUpdateProviderProtocol}
          />

          <label
            className="provider-canvas__canvas-field-label"
            htmlFor="provider-generation-api-url"
          >
            {t("providerCanvas.apiAddress.generation")}
          </label>
          <div className="provider-canvas__canvas-input-shell">
            <input
              id="provider-generation-api-url"
              className="provider-canvas__canvas-input provider-canvas__canvas-input--with-button"
              type="text"
              autoComplete="off"
              aria-label={`${providerDisplayName} API Base URL`}
              value={selectedProviderDraft.apiBaseUrl}
              placeholder={t("providerCanvas.apiAddress.placeholder")}
              onBlur={() => {
                void providerConfigState.saveSelectedProviderConfig();
              }}
              onChange={(event) =>
                providerConfigState.updateSelectedApiBaseUrl(event.target.value)
              }
            />
            {providerConfigState.isSelectedApiBaseUrlDirty ? (
              <button
                className={
                  providerConfigState.isSelectedApiBaseUrlDirty && canCompleteApiBaseUrl
                    ? "provider-canvas__canvas-input-action provider-canvas__canvas-input-action--leading"
                    : "provider-canvas__canvas-input-action"
                }
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={providerConfigState.resetSelectedApiBaseUrl}
              >
                {t("common.actions.reset")}
              </button>
            ) : null}
            <button
              className="provider-canvas__canvas-input-action provider-canvas__canvas-input-action--endpoint"
              type="button"
              disabled={!canCompleteApiBaseUrl}
              title={t("providerCanvas.apiAddress.completeEndpointTitle")}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => {
                if (!canCompleteApiBaseUrl) return;
                providerConfigState.updateSelectedApiEndpoints(
                  completedApiBaseUrl,
                  shouldCompleteModelDiscoveryUrl
                    ? completedModelDiscoveryUrl
                    : selectedProviderDraft.modelDiscoveryUrl,
                );
              }}
            >
              {t("providerCanvas.apiAddress.completeEndpoint")}
            </button>
          </div>

          <label className="provider-canvas__canvas-field-label">
            {t("providerCanvas.apiAddress.generationAuth")}
          </label>
          <OptionSelect
            ariaLabel={t("providerCanvas.apiAddress.generationAuth")}
            disabled={providerConfigState.savingProviderId !== null}
            options={PROVIDER_AUTH_SCHEME_OPTIONS}
            value={selectedProviderDraft.authScheme}
            variant="integrated-overlay"
            onChange={providerConfigState.updateSelectedAuthScheme}
          />
        </div>
      ) : (
        <div
          id="provider-api-address-panel-models"
          className="provider-canvas__canvas-field"
          role="tabpanel"
          aria-labelledby="provider-api-address-tab-models"
        >
          <label className="provider-canvas__canvas-field-label">
            {t("providerCanvas.apiAddress.modelStrategy")}
          </label>
          <OptionSelect
            ariaLabel={t("providerCanvas.apiAddress.modelStrategy")}
            disabled={providerConfigState.savingProviderId !== null}
            options={PROVIDER_MODEL_DISCOVERY_STRATEGY_OPTIONS}
            value={selectedProviderDraft.modelDiscoveryStrategy}
            variant="integrated-overlay"
            onChange={providerConfigState.updateSelectedModelDiscoveryStrategy}
          />

          <label
            className="provider-canvas__canvas-field-label"
            htmlFor="provider-model-discovery-url"
          >
            {t("providerCanvas.apiAddress.models")}
          </label>
          <div className="provider-canvas__canvas-input-shell">
            <input
              id="provider-model-discovery-url"
              className={
                providerConfigState.isSelectedModelDiscoveryUrlDirty
                  ? "provider-canvas__canvas-input provider-canvas__canvas-input--with-button"
                  : "provider-canvas__canvas-input"
              }
              type="text"
              autoComplete="off"
              aria-label={`${providerDisplayName} model discovery URL`}
              value={selectedProviderDraft.modelDiscoveryUrl}
              placeholder={t("providerCanvas.apiAddress.modelsPlaceholder")}
              onBlur={() => {
                void providerConfigState.saveSelectedProviderConfig();
              }}
              onChange={(event) =>
                providerConfigState.updateSelectedModelDiscoveryUrl(event.target.value)
              }
            />
            {providerConfigState.isSelectedModelDiscoveryUrlDirty ? (
              <button
                className="provider-canvas__canvas-input-action"
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={providerConfigState.resetSelectedModelDiscoveryUrl}
              >
                {t("common.actions.reset")}
              </button>
            ) : null}
          </div>

          <label className="provider-canvas__canvas-field-label">
            {t("providerCanvas.apiAddress.modelAuth")}
          </label>
          <OptionSelect
            ariaLabel={t("providerCanvas.apiAddress.modelAuth")}
            disabled={providerConfigState.savingProviderId !== null}
            options={PROVIDER_AUTH_SCHEME_OPTIONS}
            value={selectedProviderDraft.modelDiscoveryAuthScheme}
            variant="integrated-overlay"
            onChange={providerConfigState.updateSelectedModelDiscoveryAuthScheme}
          />
        </div>
      )}
    </div>
  );
}

export function ProviderCacheSettingsSection({
  providerConfigState,
  selectedProviderDraft,
}: ProviderConfigSectionProps) {
  const { t } = useI18n();
  const unitOptions = PROMPT_CACHE_RETENTION_UNIT_OPTIONS.map((option) => ({
    ...option,
    label: t(`providerCanvas.cacheSettings.units.${option.value}`),
  }));

  return (
    <div className="provider-canvas__canvas-group">
      <header className="provider-canvas__canvas-section-head">
        <h3 className="provider-canvas__canvas-section-title">
          {t("providerCanvas.cacheSettings.title")}
        </h3>
      </header>
      <div className="provider-canvas__canvas-field">
        <label
          className="provider-canvas__canvas-field-label"
          htmlFor="provider-prompt-cache-retention"
        >
          {t("providerCanvas.cacheSettings.retention")}
        </label>
        <div className="provider-canvas__cache-policy-row">
          <input
            id="provider-prompt-cache-retention"
            className="provider-canvas__canvas-input"
            type="number"
            inputMode="numeric"
            min="1"
            disabled={providerConfigState.savingProviderId !== null}
            value={selectedProviderDraft.promptCacheRetentionValue}
            onBlur={() => {
              void providerConfigState.saveSelectedPromptCachePolicy();
            }}
            onChange={(event) =>
              providerConfigState.updateSelectedPromptCacheRetentionValue(
                event.target.value,
              )
            }
          />
          <OptionSelect
            ariaLabel={t("providerCanvas.cacheSettings.unitAria")}
            className="provider-canvas__cache-policy-unit"
            disabled={providerConfigState.savingProviderId !== null}
            options={unitOptions}
            value={selectedProviderDraft.promptCacheRetentionUnit}
            variant="integrated-overlay"
            onChange={providerConfigState.updateSelectedPromptCacheRetentionUnit}
          />
        </div>
      </div>
    </div>
  );
}

function getProviderProtocolLabel(
  protocolFamily: ProviderProtocolFamily,
  t: ReturnType<typeof useI18n>["t"],
) {
  if (protocolFamily === "openai_responses") {
    return t("providerCatalog.protocol.openaiResponses");
  }
  if (protocolFamily === "anthropic_messages") {
    return t("providerCatalog.protocol.anthropicMessages");
  }
  if (protocolFamily === "gemini_generate_content") {
    return t("providerCatalog.protocol.geminiGenerateContent");
  }
  return t("providerCatalog.protocol.openaiCompatible");
}
