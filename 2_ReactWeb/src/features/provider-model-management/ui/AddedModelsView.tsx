import { useState } from "react";
import { PencilSimple, Pulse, X } from "@phosphor-icons/react";

import type { ProviderModelUsageSummary } from "../../../entities/llm-usage/model/providerModelUsage";
import { useI18n } from "../../../shared/i18n";
import { CUSTOM_MODEL_CAPABILITY_OPTIONS } from "../model/customModelCapabilities";
import { formatCustomModelPricingSummary } from "../model/customModelPricing";
import { formatModelSetUsageTokenValue } from "../model/providerUsageFormat";
import type {
  AddedCustomModelEntry,
  AddedModelCategoryFilter,
  UseModelManagementPanelResult,
} from "../model/useProviderModelManagement";
import { AddedModelUsageDetailsModal } from "./AddedModelUsageDetailsModal";
import { ModelManagementError } from "./ModelManagementError";
import type { ModelCheckState } from "./providerModelManagementUiTypes";
import {
  getCustomModelCapabilityLabel,
  getCustomModelPricingSummaryLabels,
} from "./providerModelI18n";

type AddedModelsViewProps = {
  hasAnyProviderApiKey: boolean;
  modelCheckStates: Record<string, ModelCheckState>;
  modelManagementPanel: UseModelManagementPanelResult;
  onTestModel: (modelId: string, label: string) => Promise<void>;
  testingModelIds: string[];
};

type AddedModelUsageDetailsState = {
  modelLabel: string;
  modelUsage: ProviderModelUsageSummary | undefined;
};

export function AddedModelsView({
  hasAnyProviderApiKey,
  modelCheckStates,
  modelManagementPanel,
  onTestModel,
  testingModelIds,
}: AddedModelsViewProps) {
  const { t } = useI18n();
  const [usageDetails, setUsageDetails] =
    useState<AddedModelUsageDetailsState | null>(null);

  return (
    <div className="provider-canvas__added-model-stack">
      <AddedModelToolbar modelManagementPanel={modelManagementPanel} />
      <ModelManagementError message={modelManagementPanel.customModelError} />
      {modelManagementPanel.isLoadingAddedCustomModels ? (
        <div className="provider-canvas__model-empty">
          {t("providerCanvas.modelManagement.added.loading")}
        </div>
      ) : modelManagementPanel.addedCustomModels.length === 0 ? (
        <div className="provider-canvas__model-empty">
          {t("providerCanvas.modelManagement.added.empty")}
        </div>
      ) : modelManagementPanel.filteredAddedCustomModels.length === 0 ? (
        <div className="provider-canvas__model-empty">
          {t("providerCanvas.modelManagement.added.emptyFiltered")}
        </div>
      ) : (
        <div className="provider-canvas__added-model-list">
          {modelManagementPanel.filteredAddedCustomModels.map((model) => {
            const modelUsage = modelManagementPanel.modelUsageByModelId.get(model.modelId);
            const modelLabel =
              model.displayName || model.modelId || t("providerCanvas.modelManagement.modelFallback");

            return (
              <AddedModelCard
                key={model.modelId}
                hasAnyProviderApiKey={hasAnyProviderApiKey}
                isDeleting={modelManagementPanel.deletingCustomModelIds.includes(model.modelId)}
                isEditing={modelManagementPanel.editingCustomModelId === model.modelId}
                isTesting={testingModelIds.includes(model.modelId)}
                model={model}
                modelCheckState={modelCheckStates[model.modelId] ?? null}
                modelUsage={modelUsage}
                onDeleteModel={modelManagementPanel.deleteCustomModel}
                onEditModel={modelManagementPanel.startEditingCustomModel}
                onOpenUsageDetails={() => setUsageDetails({ modelLabel, modelUsage })}
                onTestModel={onTestModel}
              />
            );
          })}
        </div>
      )}
      {usageDetails ? (
        <AddedModelUsageDetailsModal
          modelLabel={usageDetails.modelLabel}
          modelUsage={usageDetails.modelUsage}
          onClose={() => setUsageDetails(null)}
        />
      ) : null}
    </div>
  );
}

function AddedModelToolbar({
  modelManagementPanel,
}: {
  modelManagementPanel: UseModelManagementPanelResult;
}) {
  const { t } = useI18n();

  return (
    <div className="provider-canvas__added-model-toolbar">
      <div className="provider-canvas__added-model-search-shell">
        <input
          className="provider-canvas__canvas-input provider-canvas__added-model-search"
          type="text"
          autoComplete="off"
          aria-label={t("providerCanvas.modelManagement.added.searchAria")}
          value={modelManagementPanel.addedModelSearchQuery}
          placeholder={t("providerCanvas.modelManagement.added.searchPlaceholder")}
          onChange={(event) =>
            modelManagementPanel.updateAddedModelSearchQuery(event.target.value)
          }
        />
      </div>
      <div
        className="provider-canvas__added-model-category-bar"
        role="tablist"
        aria-label={t("providerCanvas.modelManagement.added.categoryAria")}
      >
        {(["all", ...CUSTOM_MODEL_CAPABILITY_OPTIONS.map((option) => option.value)] as const).map(
          (filter) => (
            <button
              key={filter}
              className={
                modelManagementPanel.addedModelCategoryFilter === filter
                  ? "provider-canvas__added-model-category provider-canvas__added-model-category--active"
                  : "provider-canvas__added-model-category"
              }
              type="button"
              role="tab"
              aria-selected={modelManagementPanel.addedModelCategoryFilter === filter}
              onClick={() =>
                modelManagementPanel.selectAddedModelCategoryFilter(filter)
              }
            >
              {getAddedModelCategoryLabel(filter, t)}
            </button>
          ),
        )}
      </div>
    </div>
  );
}

type AddedModelCardProps = {
  hasAnyProviderApiKey: boolean;
  isDeleting: boolean;
  isEditing: boolean;
  isTesting: boolean;
  model: AddedCustomModelEntry;
  modelCheckState: ModelCheckState | null;
  modelUsage: ProviderModelUsageSummary | undefined;
  onDeleteModel: (modelId: string) => Promise<void>;
  onEditModel: (modelId: string) => void;
  onOpenUsageDetails: () => void;
  onTestModel: (modelId: string, label: string) => Promise<void>;
};

function AddedModelCard({
  hasAnyProviderApiKey,
  isDeleting,
  isEditing,
  isTesting,
  model,
  modelCheckState,
  modelUsage,
  onDeleteModel,
  onEditModel,
  onOpenUsageDetails,
  onTestModel,
}: AddedModelCardProps) {
  const { t } = useI18n();
  const modelLabel =
    model.displayName || model.modelId || t("providerCanvas.modelManagement.modelFallback");

  return (
    <article
      className={
        isEditing
          ? "provider-canvas__added-model-card provider-canvas__added-model-card--editing"
          : "provider-canvas__added-model-card"
      }
      title={buildAddedModelTooltip(model, t)}
    >
      <div className="provider-canvas__added-model-main">
        <h4 className="provider-canvas__added-model-title">
          {model.displayName || model.modelId || t("providerCanvas.modelManagement.unnamedModel")}
        </h4>
        <AddedModelCapabilityLabels model={model} />
      </div>
      <AddedModelUsage
        modelLabel={modelLabel}
        modelUsage={modelUsage}
        onOpenDetails={onOpenUsageDetails}
      />
      <div className="provider-canvas__added-model-actions">
        <AddedModelTestControl
          hasAnyProviderApiKey={hasAnyProviderApiKey}
          isDeleting={isDeleting}
          isTesting={isTesting}
          modelCheckState={modelCheckState}
          modelId={model.modelId}
          modelLabel={modelLabel}
          onTestModel={onTestModel}
        />
        <button
          className={
            isEditing
              ? "provider-canvas__added-model-edit provider-canvas__added-model-edit--active"
              : "provider-canvas__added-model-edit"
          }
          type="button"
          aria-label={t("providerCanvas.modelManagement.added.editAria", {
            model: modelLabel,
          })}
          title={t("common.actions.edit")}
          disabled={isDeleting}
          onClick={() => onEditModel(model.modelId)}
        >
          <PencilSimple aria-hidden="true" size={14} weight="regular" />
        </button>
        <button
          className="provider-canvas__added-model-delete"
          type="button"
          aria-label={isDeleting ? t("common.actions.deleting") : t("common.actions.delete")}
          title={isDeleting ? t("common.actions.deleting") : t("common.actions.delete")}
          disabled={isDeleting}
          onClick={() => {
            void onDeleteModel(model.modelId);
          }}
        >
          <X aria-hidden="true" size={14} weight="regular" />
        </button>
      </div>
    </article>
  );
}

function AddedModelUsage({
  modelLabel,
  modelUsage,
  onOpenDetails,
}: {
  modelLabel: string;
  modelUsage: ProviderModelUsageSummary | undefined;
  onOpenDetails: () => void;
}) {
  const { t } = useI18n();

  return (
    <span className="provider-canvas__added-model-usage">
      <span className="provider-canvas__added-model-usage-total">
        <span className="provider-canvas__added-model-usage-label">
          {t("providerCanvas.modelManagement.added.tokenUsageLabel")}
        </span>
        <span className="provider-canvas__added-model-usage-value">
          {formatModelSetUsageTokenValue(modelUsage)}
        </span>
      </span>
      <button
        className="provider-canvas__added-model-usage-details"
        type="button"
        aria-label={t("providerCanvas.modelManagement.added.usageDetailsAria", {
          model: modelLabel,
        })}
        onClick={onOpenDetails}
      >
        {t("providerCanvas.modelManagement.added.details")}
      </button>
    </span>
  );
}

type AddedModelTestControlProps = {
  hasAnyProviderApiKey: boolean;
  isDeleting: boolean;
  isTesting: boolean;
  modelCheckState: ModelCheckState | null;
  modelId: string;
  modelLabel: string;
  onTestModel: (modelId: string, label: string) => Promise<void>;
};

function AddedModelTestControl({
  hasAnyProviderApiKey,
  isDeleting,
  isTesting,
  modelCheckState,
  modelId,
  modelLabel,
  onTestModel,
}: AddedModelTestControlProps) {
  const { t } = useI18n();

  if (isTesting) {
    return (
      <span
        className="provider-canvas__added-model-check-state provider-canvas__added-model-check-state--pending"
        role="status"
      >
        {t("providerCanvas.modelManagement.test.testing")}
      </span>
    );
  }

  if (modelCheckState) {
    return (
      <button
        className={
          modelCheckState.tone === "success"
            ? "provider-canvas__added-model-check-state provider-canvas__added-model-check-state--success"
            : "provider-canvas__added-model-check-state provider-canvas__added-model-check-state--error"
        }
        type="button"
        aria-label={t("providerCanvas.modelManagement.test.retestAria", {
          model: modelLabel,
        })}
        title={modelCheckState.message}
        disabled={!hasAnyProviderApiKey || isDeleting}
        onClick={() => onTestModel(modelId, modelLabel)}
      >
        {modelCheckState.tone === "success"
          ? t("providerCanvas.modelManagement.test.success")
          : t("providerCanvas.modelManagement.test.failed")}
      </button>
    );
  }

  return (
    <button
      className="provider-canvas__added-model-check"
      type="button"
      aria-label={t("providerCanvas.modelManagement.test.testAria", {
        model: modelLabel,
      })}
      title={t("providerCanvas.modelManagement.test.title")}
      disabled={!hasAnyProviderApiKey || isDeleting}
      onClick={() => onTestModel(modelId, modelLabel)}
    >
      <Pulse aria-hidden="true" size={14} weight="regular" />
    </button>
  );
}

function AddedModelCapabilityLabels({ model }: { model: AddedCustomModelEntry }) {
  const { t } = useI18n();

  if (model.capabilityTags.length === 0) {
    return null;
  }

  return (
    <span className="provider-canvas__added-model-capabilities">
      {model.capabilityTags.map((tag, index) => {
        const label = getCustomModelCapabilityLabel(tag, t);
        return (
          <span
            key={`${model.modelId}-capability-${label}`}
            className="provider-canvas__added-model-capability-item"
          >
            {index > 0 ? (
              <span
                className="provider-canvas__added-model-capability-separator"
                aria-hidden="true"
              >
                |
              </span>
            ) : null}
            <span className="provider-canvas__added-model-capability-label">
              {label}
            </span>
          </span>
        );
      })}
    </span>
  );
}

function buildAddedModelTooltip(
  model: AddedCustomModelEntry,
  t: ReturnType<typeof useI18n>["t"],
) {
  const pricingSummary = formatCustomModelPricingSummary(
    model.priceCurrency,
    model.inputPricePerMillion,
    model.cacheHitPricePerMillion,
    model.outputPricePerMillion,
    getCustomModelPricingSummaryLabels(t),
  );
  const lines = [
    model.modelId
      ? t("providerCanvas.modelManagement.added.tooltip.modelId", { value: model.modelId })
      : null,
    model.familyGroup
      ? t("providerCanvas.modelManagement.added.tooltip.group", { value: model.familyGroup })
      : null,
    model.note
      ? t("providerCanvas.modelManagement.added.tooltip.note", { value: model.note })
      : null,
    pricingSummary
      ? t("providerCanvas.modelManagement.added.tooltip.price", { value: pricingSummary })
      : null,
  ].filter((line): line is string => Boolean(line));

  return lines.length > 0 ? lines.join("\n") : undefined;
}

function getAddedModelCategoryLabel(
  filter: AddedModelCategoryFilter,
  t: ReturnType<typeof useI18n>["t"],
) {
  if (filter === "all") {
    return t("providerCanvas.modelManagement.added.all");
  }

  return getCustomModelCapabilityLabel(filter, t);
}
