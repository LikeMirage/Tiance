import type { RefObject } from "react";
import { useMemo } from "react";

import {
  PROVIDER_AUTH_SCHEME_OPTIONS,
  PROVIDER_PROTOCOL_FAMILY_OPTIONS,
} from "../../provider-config/ui/providerProtocolOptions";
import { useI18n } from "../../../shared/i18n";
import { OptionSelect } from "../../../shared/ui/option-select/OptionSelect";
import type { ProviderCreateFormDraft } from "../model/providerCreateForm";

type ProviderCatalogCreateFormProps = {
  apiBaseUrlInputRef: RefObject<HTMLInputElement | null>;
  draft: ProviderCreateFormDraft;
  error: string | null;
  isApiBaseUrlInvalid: boolean;
  isInteractive: boolean;
  isSubmitting: boolean;
  isVisible: boolean;
  onCancel: () => void;
  onSubmit: () => void;
  onUpdateField: <Field extends keyof ProviderCreateFormDraft>(
    field: Field,
    value: ProviderCreateFormDraft[Field],
  ) => void;
};

export function ProviderCatalogCreateForm({
  apiBaseUrlInputRef,
  draft,
  error,
  isApiBaseUrlInvalid,
  isInteractive,
  isSubmitting,
  isVisible,
  onCancel,
  onSubmit,
  onUpdateField,
}: ProviderCatalogCreateFormProps) {
  const { t } = useI18n();
  const protocolOptions = useMemo(
    () =>
      PROVIDER_PROTOCOL_FAMILY_OPTIONS.map((option) => ({
        ...option,
        label: getProtocolFamilyLabel(option.value, t),
      })),
    [t],
  );

  return (
    <div
      className={
        isVisible
          ? "provider-catalog-panel__create-shell provider-catalog-panel__create-shell--open"
          : "provider-catalog-panel__create-shell"
      }
      aria-hidden={!isVisible}
    >
      <section
        className="provider-catalog-panel__create"
        aria-label={t("providerCatalog.create.title")}
      >
        <div className="provider-catalog-panel__create-field">
          <label
            className="provider-catalog-panel__create-label"
            htmlFor="provider-create-name"
          >
            {t("providerCatalog.create.providerName")}
          </label>
          <input
            id="provider-create-name"
            className="provider-catalog-panel__create-input"
            type="text"
            autoComplete="off"
            value={draft.displayName}
            placeholder={t("providerCatalog.create.providerNamePlaceholder")}
            disabled={!isInteractive}
            onChange={(event) =>
              onUpdateField("displayName", event.target.value)
            }
          />
        </div>

        <div className="provider-catalog-panel__create-field">
          <label
            className="provider-catalog-panel__create-label"
            htmlFor="provider-create-api-base-url"
          >
            {t("providerCatalog.create.apiBaseUrl")}
          </label>
          <input
            id="provider-create-api-base-url"
            ref={apiBaseUrlInputRef}
            className={
              isApiBaseUrlInvalid
                ? "provider-catalog-panel__create-input provider-catalog-panel__create-input--invalid"
                : "provider-catalog-panel__create-input"
            }
            type="text"
            autoComplete="off"
            value={draft.apiBaseUrl}
            placeholder="https://example.com/v1/chat/completions"
            aria-invalid={isApiBaseUrlInvalid}
            disabled={!isInteractive}
            onChange={(event) =>
              onUpdateField("apiBaseUrl", event.target.value)
            }
          />
        </div>

        <div className="provider-catalog-panel__create-field">
          <span
            className="provider-catalog-panel__create-label"
            id="provider-create-protocol-label"
          >
            {t("providerCatalog.create.protocol")}
          </span>
          <OptionSelect
            ariaLabelledBy="provider-create-protocol-label"
            disabled={!isInteractive}
            options={protocolOptions}
            value={draft.protocolFamily}
            variant="integrated-overlay"
            onChange={(value) => onUpdateField("protocolFamily", value)}
          />
        </div>

        <div className="provider-catalog-panel__create-field">
          <span
            className="provider-catalog-panel__create-label"
            id="provider-create-auth-label"
          >
            {t("providerCatalog.create.auth")}
          </span>
          <OptionSelect
            ariaLabelledBy="provider-create-auth-label"
            disabled={!isInteractive}
            options={PROVIDER_AUTH_SCHEME_OPTIONS}
            value={draft.authScheme}
            variant="integrated-overlay"
            onChange={(value) => onUpdateField("authScheme", value)}
          />
        </div>

        {error ? (
          <div className="provider-catalog-panel__create-feedback" role="status">
            {error}
          </div>
        ) : null}

        <div className="provider-catalog-panel__create-actions">
          <button
            className="provider-catalog-panel__create-button"
            type="button"
            onClick={onCancel}
            disabled={!isVisible || isSubmitting}
          >
            {t("common.actions.cancel")}
          </button>
          <button
            className="provider-catalog-panel__create-button provider-catalog-panel__create-button--primary"
            type="button"
            onClick={onSubmit}
            disabled={!isVisible || isSubmitting}
          >
            {isSubmitting ? t("common.actions.saving") : t("common.actions.save")}
          </button>
        </div>
      </section>
    </div>
  );
}

function getProtocolFamilyLabel(
  value: (typeof PROVIDER_PROTOCOL_FAMILY_OPTIONS)[number]["value"],
  t: ReturnType<typeof useI18n>["t"],
) {
  switch (value) {
    case "openai_compatible":
      return t("providerCatalog.protocol.openaiCompatible");
    case "openai_responses":
      return t("providerCatalog.protocol.openaiResponses");
    case "anthropic_messages":
      return t("providerCatalog.protocol.anthropicMessages");
    case "gemini_generate_content":
      return t("providerCatalog.protocol.geminiGenerateContent");
  }
}
