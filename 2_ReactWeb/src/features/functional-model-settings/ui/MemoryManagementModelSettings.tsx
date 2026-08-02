import { useI18n } from "../../../shared/i18n";
import {
  DEFAULT_LONG_TERM_MEMORY_FAILURE_RETRY_COUNT,
  MAX_LONG_TERM_MEMORY_FAILURE_RETRY_COUNT,
} from "../model/functionalModelSettings";
import { FunctionalModelProfileSettingsForm } from "./FunctionalModelProfileSettingsForm";

type MemoryManagementModelSettingsProps = {
  defaultTriggerTokenThreshold: number;
  profileKey: "projectMemoryManagement" | "globalMemoryManagement";
  sectionKey: "projectMemoryManagement" | "globalMemoryManagement";
};

export function ProjectMemoryManagementModelSettings() {
  return (
    <MemoryManagementModelSettings
      defaultTriggerTokenThreshold={50_000}
      profileKey="projectMemoryManagement"
      sectionKey="projectMemoryManagement"
    />
  );
}

export function GlobalMemoryManagementModelSettings() {
  return (
    <MemoryManagementModelSettings
      defaultTriggerTokenThreshold={100_000}
      profileKey="globalMemoryManagement"
      sectionKey="globalMemoryManagement"
    />
  );
}

function MemoryManagementModelSettings({
  defaultTriggerTokenThreshold,
  profileKey,
  sectionKey,
}: MemoryManagementModelSettingsProps) {
  const { t } = useI18n();
  const titleKey = `functionalModelSettings.sections.${sectionKey}` as const;
  const triggerDescriptionKey = (
    profileKey === "projectMemoryManagement"
      ? "functionalModelSettings.longTermMemoryManagement.projectTriggerTokenDescription"
      : "functionalModelSettings.longTermMemoryManagement.globalTriggerTokenDescription"
  );

  return (
    <FunctionalModelProfileSettingsForm
      additionalBooleanFields={[
        {
          description: t(
            "functionalModelSettings.longTermMemoryManagement.blockingDescription",
          ),
          key: "blockingEnabled",
          label: t(
            "functionalModelSettings.longTermMemoryManagement.blockingEnabled",
          ),
        },
      ]}
      additionalNumberFields={[
        {
          defaultValue: defaultTriggerTokenThreshold,
          description: t(triggerDescriptionKey),
          key: "triggerTokenThreshold",
          label: t(
            "functionalModelSettings.longTermMemoryManagement.triggerTokenThreshold",
          ),
          min: 1,
          step: 1000,
        },
        {
          defaultValue: DEFAULT_LONG_TERM_MEMORY_FAILURE_RETRY_COUNT,
          description: t(
            "functionalModelSettings.longTermMemoryManagement.failureRetryDescription",
          ),
          key: "failureRetryCount",
          label: t(
            "functionalModelSettings.longTermMemoryManagement.failureRetryCount",
          ),
          max: MAX_LONG_TERM_MEMORY_FAILURE_RETRY_COUNT,
          min: 0,
          step: 1,
        },
      ]}
      hideGenerationControlsForSessionModel
      modelAriaLabel={t(titleKey)}
      profileKey={profileKey}
      sessionModelOption={{
        description: t(
          "functionalModelSettings.longTermMemoryManagement.cacheHitOptimizationDescription",
        ),
        groupLabel: t(
          "functionalModelSettings.longTermMemoryManagement.modelModeGroup",
        ),
        label: t(
          "functionalModelSettings.longTermMemoryManagement.cacheHitOptimizationMode",
        ),
        notes: [
          t(
            "functionalModelSettings.longTermMemoryManagement.cacheHitOptimizationSettingsNote",
          ),
          t(
            "functionalModelSettings.longTermMemoryManagement.cacheHitOptimizationBoundaryNote",
          ),
        ],
        reasoningPlaceholder: t(
          "functionalModelSettings.longTermMemoryManagement.sessionReasoningPlaceholder",
        ),
      }}
      showOutputFormatControl={false}
      title={t(titleKey)}
      titleId={`functional-models-${sectionKey}-title`}
    />
  );
}
