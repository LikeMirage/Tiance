import { useEffect } from "react";
import { X } from "@phosphor-icons/react";

import type { ProviderModelUsageSummary } from "../../../entities/llm-usage/model/providerModelUsage";
import { useI18n } from "../../../shared/i18n";
import {
  getModelSetUsageMetrics,
  resolveProviderUsageFeatureKey,
} from "../model/providerUsageFormat";
import { getProviderUsageMetricLabels } from "./providerModelI18n";

type AddedModelUsageDetailsModalProps = {
  modelLabel: string;
  modelUsage: ProviderModelUsageSummary | undefined;
  onClose: () => void;
};

export function AddedModelUsageDetailsModal({
  modelLabel,
  modelUsage,
  onClose,
}: AddedModelUsageDetailsModalProps) {
  const { t } = useI18n();
  const featureSummaries = modelUsage?.by_features ?? [];
  const metricLabels = getProviderUsageMetricLabels(t);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div
      className="provider-canvas__usage-details-backdrop"
      role="presentation"
      onClick={onClose}
    >
      <section
        className="provider-canvas__usage-details-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="provider-canvas-usage-details-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="provider-canvas__usage-details-header">
          <div className="provider-canvas__usage-details-heading">
            <span className="provider-canvas__usage-details-kicker">
              {t("providerCanvas.modelManagement.usageDetails.title")}
            </span>
            <h3
              id="provider-canvas-usage-details-title"
              className="provider-canvas__usage-details-title"
            >
              {modelLabel}
            </h3>
          </div>
          <button
            className="provider-canvas__usage-details-close"
            type="button"
            aria-label={t("providerCanvas.modelManagement.usageDetails.closeAria")}
            onClick={onClose}
          >
            <X aria-hidden="true" size={16} weight="regular" />
          </button>
        </header>
        <div className="provider-canvas__usage-details-body">
          <UsageDetailsRow
            label={t("providerCanvas.modelManagement.usageDetails.allUsage")}
            metricLabels={metricLabels}
            summary={modelUsage}
          />
          <div className="provider-canvas__usage-details-section">
            <h4 className="provider-canvas__usage-details-section-title">
              {t("providerCanvas.modelManagement.usageDetails.byUsage")}
            </h4>
            {featureSummaries.length > 0 ? (
              <div className="provider-canvas__usage-details-rows">
                {featureSummaries.map((feature) => (
                  <UsageDetailsRow
                    key={`${feature.model_id}-${feature.usage_feature_key ?? "main_chat"}`}
                    label={
                      feature.usage_feature_display_name
                        || getUsageFeatureLabel(feature.usage_feature_key, t)
                    }
                    metricLabels={metricLabels}
                    summary={feature}
                  />
                ))}
              </div>
            ) : (
              <p className="provider-canvas__usage-details-empty">
                {t("providerCanvas.modelManagement.usageDetails.empty")}
              </p>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

function getUsageFeatureLabel(
  value: string | null | undefined,
  t: ReturnType<typeof useI18n>["t"],
) {
  const featureKey = resolveProviderUsageFeatureKey(value);
  if (featureKey === "conversationNaming") {
    return t("providerCanvas.modelManagement.usageFeatures.conversationNaming");
  }
  if (featureKey === "memoryCompression") {
    return t("providerCanvas.modelManagement.usageFeatures.memoryCompression");
  }
  if (featureKey === "projectMemoryManagement") {
    return t("providerCanvas.modelManagement.usageFeatures.projectMemoryManagement");
  }
  if (featureKey === "globalMemoryManagement") {
    return t("providerCanvas.modelManagement.usageFeatures.globalMemoryManagement");
  }
  return t("providerCanvas.modelManagement.usageFeatures.mainChat");
}

function UsageDetailsRow({
  label,
  metricLabels,
  summary,
}: {
  label: string;
  metricLabels: Record<string, string>;
  summary: ProviderModelUsageSummary | undefined;
}) {
  return (
    <div className="provider-canvas__usage-details-row">
      <span className="provider-canvas__usage-details-row-label">{label}</span>
      <span className="provider-canvas__usage-details-row-metrics">
        {getModelSetUsageMetrics(summary).map((metric) => (
          <span
            key={`${label}-${metric.key}`}
            className="provider-canvas__usage-details-metric"
          >
            <span className="provider-canvas__usage-details-metric-label">
              {metricLabels[metric.key]}
            </span>
            <span className="provider-canvas__usage-details-metric-value">
              {metric.value}
            </span>
          </span>
        ))}
      </span>
    </div>
  );
}
