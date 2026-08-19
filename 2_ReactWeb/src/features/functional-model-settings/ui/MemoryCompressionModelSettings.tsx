import { useI18n } from "../../../shared/i18n";
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
