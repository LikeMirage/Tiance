import {
  CUSTOM_MODEL_CAPABILITY_OPTIONS,
} from "../model/customModelCapabilities";
import type { UseModelManagementPanelResult } from "../model/useProviderModelManagement";
import { OptionSelect } from "../../../shared/ui/option-select/OptionSelect";
import { useI18n } from "../../../shared/i18n";
import { ModelManagementError } from "./ModelManagementError";
import {
  getCustomModelCapabilityLabel,
  getCustomModelPriceCurrencyOptions,
} from "./providerModelI18n";

type CustomModelEditorProps = {
  modelManagementPanel: UseModelManagementPanelResult;
  providerId: string;
};

export function CustomModelEditor({
  modelManagementPanel,
  providerId,
}: CustomModelEditorProps) {
  const { t } = useI18n();

  return (
    <div className="provider-canvas__custom-model-panel">
      <CustomModelTextField
        disabled={Boolean(modelManagementPanel.editingCustomModelId)}
        id={`${providerId}-custom-model-id`}
        isReadonly={Boolean(modelManagementPanel.editingCustomModelId)}
        label={t("providerCanvas.modelManagement.custom.modelId")}
        placeholder={t("providerCanvas.modelManagement.custom.modelIdPlaceholder")}
        value={modelManagementPanel.customModelDraft.modelId}
        onBlur={modelManagementPanel.inferCustomModelCapabilities}
        onChange={(value) => modelManagementPanel.updateCustomModelDraft("modelId", value)}
      />
      <CustomModelTextField
        id={`${providerId}-custom-model-name`}
        label={t("providerCanvas.modelManagement.custom.modelName")}
        placeholder={t("providerCanvas.modelManagement.custom.modelNamePlaceholder")}
        value={modelManagementPanel.customModelDraft.displayName}
        onBlur={modelManagementPanel.inferCustomModelCapabilities}
        onChange={(value) => modelManagementPanel.updateCustomModelDraft("displayName", value)}
      />
      <CustomModelTextField
        id={`${providerId}-custom-model-group`}
        label={t("providerCanvas.modelManagement.custom.modelGroup")}
        placeholder={t("providerCanvas.modelManagement.custom.modelGroupPlaceholder")}
        value={modelManagementPanel.customModelDraft.familyGroup}
        onChange={(value) => modelManagementPanel.updateCustomModelDraft("familyGroup", value)}
      />
      <div className="provider-canvas__custom-model-field">
        <label
          className="provider-canvas__custom-model-label"
          htmlFor={`${providerId}-custom-model-note`}
        >
          {t("providerCanvas.modelManagement.custom.note")}
        </label>
        <textarea
          id={`${providerId}-custom-model-note`}
          className="provider-canvas__canvas-input provider-canvas__custom-model-textarea"
          autoComplete="off"
          value={modelManagementPanel.customModelDraft.note}
          placeholder={t("providerCanvas.modelManagement.custom.notePlaceholder")}
          rows={2}
          onChange={(event) =>
            modelManagementPanel.updateCustomModelDraft("note", event.target.value)
          }
        />
      </div>
      <CustomModelPriceFields modelManagementPanel={modelManagementPanel} />
      <ModelManagementError message={modelManagementPanel.customModelError} />
      <CustomModelCapabilityFields modelManagementPanel={modelManagementPanel} />
      <div className="provider-canvas__custom-model-actions">
        <button
          className="provider-canvas__custom-model-action"
          type="button"
          disabled={modelManagementPanel.isSavingCustomModel}
          onClick={modelManagementPanel.clearCustomModelDraft}
        >
          {modelManagementPanel.editingCustomModelId
            ? t("common.actions.cancel")
            : t("common.actions.clear")}
        </button>
        <button
          className="provider-canvas__custom-model-action provider-canvas__custom-model-action--primary"
          type="button"
          disabled={!modelManagementPanel.canSaveCustomModelDraft}
          onClick={() => {
            void modelManagementPanel.saveCustomModelDraft();
          }}
        >
          {modelManagementPanel.isSavingCustomModel
            ? t("common.actions.saving")
            : modelManagementPanel.editingCustomModelId
              ? t("providerCanvas.modelManagement.custom.saveChanges")
              : t("providerCanvas.modelManagement.custom.add")}
        </button>
      </div>
    </div>
  );
}

type CustomModelTextFieldProps = {
  disabled?: boolean;
  id: string;
  isReadonly?: boolean;
  label: string;
  onBlur?: () => void;
  onChange: (value: string) => void;
  placeholder: string;
  value: string;
};

function CustomModelTextField({
  disabled = false,
  id,
  isReadonly = false,
  label,
  onBlur,
  onChange,
  placeholder,
  value,
}: CustomModelTextFieldProps) {
  return (
    <div className="provider-canvas__custom-model-field">
      <label className="provider-canvas__custom-model-label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className={
          isReadonly
            ? "provider-canvas__canvas-input provider-canvas__canvas-input--readonly"
            : "provider-canvas__canvas-input"
        }
        type="text"
        autoComplete="off"
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        onBlur={onBlur}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function CustomModelPriceFields({
  modelManagementPanel,
}: {
  modelManagementPanel: UseModelManagementPanelResult;
}) {
  const { t } = useI18n();

  return (
    <div className="provider-canvas__custom-model-field">
      <span className="provider-canvas__custom-model-label">
        {t("providerCanvas.modelManagement.custom.price")}
      </span>
      <div className="provider-canvas__custom-model-price-row">
        <OptionSelect
          ariaLabel={t("providerCanvas.modelManagement.custom.priceCurrencyAria")}
          className="provider-canvas__custom-model-price-currency"
          options={getCustomModelPriceCurrencyOptions(t)}
          value={modelManagementPanel.customModelDraft.priceCurrency}
          onChange={(value) =>
            modelManagementPanel.updateCustomModelDraft("priceCurrency", value)
          }
        />
        <CustomModelPriceInput
          ariaLabel={t("providerCanvas.modelManagement.custom.inputPrice")}
          placeholder={t("providerCanvas.modelManagement.custom.inputPricePlaceholder")}
          value={modelManagementPanel.customModelDraft.inputPricePerMillion}
          onChange={(value) =>
            modelManagementPanel.updateCustomModelDraft("inputPricePerMillion", value)
          }
        />
        <CustomModelPriceInput
          ariaLabel={t("providerCanvas.modelManagement.custom.cacheHitPrice")}
          placeholder={t("providerCanvas.modelManagement.custom.cacheHitPricePlaceholder")}
          value={modelManagementPanel.customModelDraft.cacheHitPricePerMillion}
          onChange={(value) =>
            modelManagementPanel.updateCustomModelDraft("cacheHitPricePerMillion", value)
          }
        />
        <CustomModelPriceInput
          ariaLabel={t("providerCanvas.modelManagement.custom.outputPrice")}
          placeholder={t("providerCanvas.modelManagement.custom.outputPricePlaceholder")}
          value={modelManagementPanel.customModelDraft.outputPricePerMillion}
          onChange={(value) =>
            modelManagementPanel.updateCustomModelDraft("outputPricePerMillion", value)
          }
        />
      </div>
    </div>
  );
}

type CustomModelPriceInputProps = {
  ariaLabel: string;
  onChange: (value: string) => void;
  placeholder: string;
  value: string;
};

function CustomModelPriceInput({
  ariaLabel,
  onChange,
  placeholder,
  value,
}: CustomModelPriceInputProps) {
  return (
    <input
      className="provider-canvas__canvas-input"
      type="text"
      inputMode="decimal"
      autoComplete="off"
      aria-label={ariaLabel}
      value={value}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

function CustomModelCapabilityFields({
  modelManagementPanel,
}: {
  modelManagementPanel: UseModelManagementPanelResult;
}) {
  const { t } = useI18n();

  return (
    <div className="provider-canvas__custom-model-field">
      <span className="provider-canvas__custom-model-label">
        {t("providerCanvas.modelManagement.custom.capabilities")}
      </span>
      <div className="provider-canvas__custom-model-capability-row">
        {CUSTOM_MODEL_CAPABILITY_OPTIONS.map((option) => {
          const isActive =
            modelManagementPanel.customModelDraft.capabilityTags.includes(option.value);

          return (
            <button
              key={option.value}
              className={
                isActive
                  ? "provider-canvas__custom-model-capability provider-canvas__custom-model-capability--active"
                  : "provider-canvas__custom-model-capability"
              }
              type="button"
              aria-pressed={isActive}
              onClick={() =>
                modelManagementPanel.toggleCustomModelCapability(option.value)
              }
            >
              {getCustomModelCapabilityLabel(option.value, t)}
            </button>
          );
        })}
      </div>
    </div>
  );
}
