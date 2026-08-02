import { useI18n } from "../../../shared/i18n";
import { FunctionalModelProfileSettingsForm } from "./FunctionalModelProfileSettingsForm";

export function ConversationNamingModelSettings() {
  const { t } = useI18n();

  return (
    <FunctionalModelProfileSettingsForm
      additionalNumberFields={[
        {
          defaultValue: 20_000,
          description: t("functionalModelSettings.conversationNaming.triggerTokenDescription"),
          key: "triggerTokenThreshold",
          label: t("functionalModelSettings.conversationNaming.triggerTokenThreshold"),
          min: 1,
          step: 1000,
        },
      ]}
      hideGenerationControlsForSessionModel
      modelAriaLabel={t("functionalModelSettings.sections.conversationNaming")}
      profileKey="naming"
      sessionModelOption={{
        description: t("functionalModelSettings.conversationNaming.cacheHitOptimizationDescription"),
        groupLabel: t("functionalModelSettings.conversationNaming.modelModeGroup"),
        label: t("functionalModelSettings.conversationNaming.cacheHitOptimizationMode"),
        notes: [
          t("functionalModelSettings.conversationNaming.cacheHitOptimizationSettingsNote"),
          t("functionalModelSettings.conversationNaming.cacheHitOptimizationBoundaryNote"),
        ],
        reasoningPlaceholder: t("functionalModelSettings.conversationNaming.sessionReasoningPlaceholder"),
      }}
      showOutputFormatControl={false}
      title={t("functionalModelSettings.sections.conversationNaming")}
      titleId="functional-models-conversation-naming-title"
    />
  );
}
