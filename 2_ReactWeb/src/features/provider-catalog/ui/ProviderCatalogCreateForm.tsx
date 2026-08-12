import type { RefObject } from "react";
import { useI18n } from "../../../shared/i18n";
import type { ProviderCreateFormDraft } from "../model/providerCreateForm";

type ProviderCatalogCreateFormProps = {
  displayNameInputRef: RefObject<HTMLInputElement | null>;
  draft: ProviderCreateFormDraft;
  error: string | null;
  isDisplayNameInvalid: boolean;
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
  displayNameInputRef,
  draft,
  error,
  isDisplayNameInvalid,
  isInteractive,
  isSubmitting,
  isVisible,
  onCancel,
  onSubmit,
  onUpdateField,
}: ProviderCatalogCreateFormProps) {
  const { t } = useI18n();

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
            ref={displayNameInputRef}
            className={
              isDisplayNameInvalid
                ? "provider-catalog-panel__create-input provider-catalog-panel__create-input--invalid"
                : "provider-catalog-panel__create-input"
            }
            type="text"
            autoComplete="off"
            value={draft.displayName}
            placeholder={t("providerCatalog.create.providerNamePlaceholder")}
            aria-invalid={isDisplayNameInvalid}
            disabled={!isInteractive}
            onChange={(event) =>
              onUpdateField("displayName", event.target.value)
            }
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
