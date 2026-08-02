import { useI18n } from "../../../shared/i18n";
import {
  DEFAULT_MEMORY_COMPRESSION_FAILURE_RETRY_COUNT,
  MAX_MEMORY_COMPRESSION_FAILURE_RETRY_COUNT,
} from "../model/functionalModelSettings";
import { FunctionalModelProfileSettingsForm } from "./FunctionalModelProfileSettingsForm";

export function MemoryCompressionModelSettings() {
  const { t } = useI18n();

  return (
    <FunctionalModelProfileSettingsForm
      additionalBooleanFields={[
        {
          description: t("functionalModelSettings.memoryCompression.blockingDescription"),
          key: "blockingEnabled",
          label: t("functionalModelSettings.memoryCompression.blockingEnabled"),
        },
      ]}
      additionalNumberFields={[
        {
          defaultValue: DEFAULT_MEMORY_COMPRESSION_FAILURE_RETRY_COUNT,
          description: t("functionalModelSettings.memoryCompression.failureRetryDescription"),
          key: "failureRetryCount",
          label: t("functionalModelSettings.memoryCompression.failureRetryCount"),
          max: MAX_MEMORY_COMPRESSION_FAILURE_RETRY_COUNT,
          min: 0,
          step: 1,
        },
      ]}
      hideGenerationControlsForSessionModel
      modelAriaLabel={t("functionalModelSettings.sections.memoryCompression")}
      promptTabs={[
        {
          key: "prompt",
          label: t("functionalModelSettings.memoryCompression.prompt"),
        },
      ]}
      profileKey="memoryCompression"
      sessionModelOption={{
        description: t("functionalModelSettings.memoryCompression.cacheHitOptimizationDescription"),
        groupLabel: t("functionalModelSettings.memoryCompression.modelModeGroup"),
        label: t("functionalModelSettings.memoryCompression.cacheHitOptimizationMode"),
        notes: [
          t("functionalModelSettings.memoryCompression.cacheHitOptimizationSettingsNote"),
          t("functionalModelSettings.memoryCompression.cacheHitOptimizationBoundaryNote"),
        ],
        reasoningPlaceholder: t("functionalModelSettings.memoryCompression.sessionReasoningPlaceholder"),
      }}
      showOutputFormatControl={false}
      title={t("functionalModelSettings.sections.memoryCompression")}
      titleId="functional-models-memory-compression-title"
    />
  );
}
